import os
import json
import datetime

####################################################################################################
# Third‑Party Libraries                                                                           #
####################################################################################################
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints  # noqa: E402
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *  # noqa: F403,E402
from ctrader_open_api.messages.OpenApiMessages_pb2 import *  # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *  # noqa: F403,E402
from twisted.internet import reactor, defer, task  # Twisted = event‑loop used by cTrader SDK
from google.protobuf.json_format import MessageToDict  # Convert Protobuf→dict for convenience

####################################################################################################
# Helper Functions                                                                                #
####################################################################################################

def path(folder: str = '', file: str = '') -> str:
    """Return an OS‑agnostic *absolute* path for *folder/file* under CWD.

    Examples
    --------
    >>> path('config', 'cred.json')
    '/home/user/project/config/cred.json'
    """
    return os.path.join(os.getcwd(), folder, file).replace(os.sep, '/')


def get_json(folder: str, file_name: str):
    """Safely load a JSON file; return **None** on failure (with logged error)."""
    try:
        with open(path(folder, f"{file_name}.json")) as fp:
            return json.load(fp)
    except Exception as exc:
        print('JSON load error:', exc)
        return None

####################################################################################################
# Credentials & Static Config                                                                     #
####################################################################################################
# IMPORTANT: Never commit real secrets. Use env‑vars or a secrets‑manager.
# If you wish to load from disk instead, un‑comment the line below and delete the hard‑coded dict.
CREDENTIALS = get_json('Desktop', 'CREDENTIALS')

# Map FIX symbol‑IDs to human‑readable names that we’ll print with each bar.
SYMBOL_IDS = [10026, 10029, 10028]#, 1, 2, 4]
SYMBOL_NAMES = ['BTCUSD', 'ETHUSD', 'BCHUSD']#, 'EURUSD', 'GBPUSD', 'USDJPY']

# Chosen timeframe. cTrader uses enumerations (see mapping below).
TIMEFRAME = 'M1'

####################################################################################################
# Timeframe ↔︎ helper look‑ups                                                                     #
####################################################################################################
Timeframe_ProtoOATrendbarPeriod = {
    'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4, 'M5': 5,
    'M10': 6, 'M15': 7, 'M30': 8, 'H1': 9, 'H4': 10,
    'H12': 11, 'D1': 12, 'W1': 13,
}

# Minutes in each timeframe – used to compute bar timestamps.
Timeframe_Minutes = {
    'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4, 'M5': 5,
    'M10': 10, 'M15': 15, 'M30': 30, 'H1': 60, 'H4': 240,
    'H12': 720, 'D1': 1440, 'W1': 10080,
}

####################################################################################################
# Symbol Class                                                                                    #
####################################################################################################

class Symbol:
    """Light wrapper that tracks the latest OHLC bar for a single instrument."""

    # Class (shared) attributes so we can detect when a completely new bar
    # starts for *all* subscribed symbols.
    ts: int = 0           # Timestamp bucket of the *previous* closed bar
    new_bar: bool = False # Becomes **True** exactly once per bar across assets

    # ------------------------------------------------------------------
    # Instance initialiser
    # ------------------------------------------------------------------
    def __init__(self, symbol_id: int, symbol_name: str):
        self.symbol_id = symbol_id
        self.symbol_name = symbol_name
        # OHLC placeholders (prices come in ‑> /100000.0 per docs)
        self.open = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.bar = None  # Convenience list for printing

    # ------------------------------------------------------------------
    # Main per‑symbol event‑loop triggered for EVERY incoming message
    # after being converted to a Python dict.
    # ------------------------------------------------------------------
    async def run(self, msg: dict):
        # 1 - If *a* new bar just closed (regardless of symbol), print ours.
        if Symbol.new_bar:
            self.bar = [
                self.symbol_name,
                str(datetime.datetime.fromtimestamp(Symbol.ts * Timeframe_Minutes[TIMEFRAME] * 60)),
                self.open, self.high, self.low, self.close,  # OHLC just closed
            ]
            print(self.bar)
            return  # nothing else to do on *this* message

        # 2 - Otherwise, update OHLC if this message belongs to this symbol
        #      and is a *trendbar* update (i.e. partial progress of current bar).
        cond = (
            msg.get('symbolId') == str(self.symbol_id)
            and 'trendbar' in msg
            and 'sessionClose' not in msg
        )
        if not cond:
            return

        # Flatten nested fields (the Open API nests price deltas under trendbar[0])
        msg['low'] = msg['trendbar'][0]['low']
        msg['deltaOpen'] = msg['trendbar'][0]['deltaOpen']
        msg['deltaHigh'] = msg['trendbar'][0]['deltaHigh']
        del msg['trendbar']

        # Ensure all numerics are *actually* numbers.
        for key, val in msg.items():
            if isinstance(val, str):
                msg[key] = eval(val)  # noqa: S307 – SDK returns numerics as strings

        # Update running OHLC (convert 1/100k pips → price)
        self.low = msg['low'] / 100000.0
        self.open = (msg['low'] + msg['deltaOpen']) / 100000.0
        self.high = (msg['low'] + msg['deltaHigh']) / 100000.0
        self.close = msg['bid'] / 100000.0

    # ------------------------------------------------------------------
    # Class helper to detect the transition M‑1 → M (a brand‑new bar)
    # ------------------------------------------------------------------
    @classmethod
    async def check_new_bar(cls, msg: dict):
        # Bar index = floor(timestamp / bar‑ms)
        bar_index = int(msg['timestamp']) // (Timeframe_Minutes[TIMEFRAME] * 60000) - 1

        if bar_index != cls.ts and cls.ts != 0:
            # We’ve just rolled over to a new bar!
            cls.ts = bar_index
            cls.new_bar = True
            dt = datetime.datetime.fromtimestamp(cls.ts * Timeframe_Minutes[TIMEFRAME] * 60)
            print(f"\nNew Bar closed @ {dt}\n")
        else:
            # First time initialisation or still within the same bar.
            if cls.ts == 0:
                cls.ts = bar_index
            cls.new_bar = False

####################################################################################################
# Twisted (event‑driven) Callbacks                                                                #
####################################################################################################

def on_message_received(client: Client, message):
    """Convert Protobuf message → dict and dispatch to Symbol workers."""
    if message.payloadType == 2131:  # 2131 == ProtoOASpotEvent (bid/ask & trendbar)
        dict_msg = MessageToDict(Protobuf.extract(message))
        # Kick off coroutine(s) without blocking Twisted loop.
        defer.ensureDeferred(mainloop(dict_msg))


async def mainloop(dict_msg):
    """Single dispatcher that first checks *global* bar rollover, then updates each symbol."""
    await Symbol.check_new_bar(dict_msg)
    for sym in SYMBOLS:
        await sym.run(dict_msg)

####################################################################################################
# Helper: subscribe to live trendbars for one symbol                                              #
####################################################################################################
async def subscribe_trendbars(symbol_id: int, account_id: int):
    req = ProtoOASubscribeLiveTrendbarReq()
    req.ctidTraderAccountId = account_id
    req.period = Timeframe_ProtoOATrendbarPeriod[TIMEFRAME]
    req.symbolId = symbol_id
    _ = CLIENT.send(req)  # Fire‑and‑forget
    print(f"Subscribed to {SYMBOL_NAMES[SYMBOL_IDS.index(symbol_id)]}")

####################################################################################################
# Misc utilities                                                                                 #
####################################################################################################

def sleep(secs: float):
    """Non‑blocking sleep helper compatible with Twisted reactor."""
    return task.deferLater(reactor, secs, lambda: None)

####################################################################################################
# Authentication & Subscription Flow                                                             #
####################################################################################################
@defer.inlineCallbacks
def account_auth_response(result):
    print("Account authenticated\n")

    # Subscribe to *spot* price updates for all symbols (includes bid/ask + timestamps).
    spot_req = ProtoOASubscribeSpotsReq()
    spot_req.ctidTraderAccountId = CREDENTIALS["AccountId"]
    spot_req.symbolId.extend(SYMBOL_IDS)
    spot_req.subscribeToSpotTimestamp = True
    _ = CLIENT.send(spot_req)

    # Subscribe to trendbars for each symbol with a tiny stagger to avoid rate limits.
    for idx, sym_id in enumerate(SYMBOL_IDS):
        defer.ensureDeferred(subscribe_trendbars(sym_id, CREDENTIALS["AccountId"]))
        yield sleep(0.5 if idx < len(SYMBOL_IDS) - 1 else 0)
    print("Subscribed to all symbols!")


def application_auth_response(_result):
    print("Application authenticated")
    req = ProtoOAAccountAuthReq()
    req.ctidTraderAccountId = CREDENTIALS["AccountId"]
    req.accessToken = CREDENTIALS["AccessToken"]
    deferred = CLIENT.send(req)
    deferred.addCallbacks(account_auth_response, on_error)

####################################################################################################
# Generic error & connection handlers                                                            #
####################################################################################################

def on_error(_client, failure):
    print("Message Error:", failure)


def disconnected(_client, reason):
    print("Disconnected:", reason)


def connected(_client):
    print("TCP connected – authenticating…")
    req = ProtoOAApplicationAuthReq()
    req.clientId = CREDENTIALS["ClientId"]
    req.clientSecret = CREDENTIALS["Secret"]
    deferred = CLIENT.send(req)
    deferred.addCallbacks(application_auth_response, on_error)

####################################################################################################
# Bootstrap                                                                                      #
####################################################################################################
# Pick host based on demo/live flag.
HOST = EndPoints.PROTOBUF_LIVE_HOST if CREDENTIALS["HostType"].lower() == "live" else EndPoints.PROTOBUF_DEMO_HOST

# Instantiate TCP client from the cTrader SDK.
CLIENT = Client(HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)

# Create Symbol objects so we can track OHLC per instrument.
SYMBOLS = [Symbol(sid, sname) for sid, sname in zip(SYMBOL_IDS, SYMBOL_NAMES)]

# Wire up callbacks and start the service.
CLIENT.setConnectedCallback(connected)
CLIENT.setDisconnectedCallback(disconnected)
CLIENT.setMessageReceivedCallback(on_message_received)

CLIENT.startService()
reactor.run()  # hand over control to Twisted’s event‑loop