import websocket
import json
import time
import threading
import requests
import pandas as pd
import numpy as np
from binance.client import Client
from binance.exceptions import BinanceAPIException

# futures_balance = client_live.futures_account_balance()
# usdt_balance = next(item for item in futures_balance if item["asset"] == "USDT")
# print("Số dư USDT Futures:", usdt_balance)


live_api_key = 'rYMIltVKpbWP4XyYRDDJrt3uZ2gkmVU9v6S5HnVKSMZtN5i0BNEAe01wgtTBfVsT'
live_api_secret = 'S3DMpl3SuP4WI5JTODs1p1u5NOiATOmdELcgrNt8fggDqSXnrS1ibFBEZlyquAv6'
client_live = Client(live_api_key, live_api_secret)

# 🔹 Cấu hình giao dịch
SYMBOL = "SUIUSDT"
TIMEFRAME = "5m" 
LEVERAGE = 15
RISK_AMOUNT = 1.5  # Rủi ro cố định mỗi giao dịch (1R)
RR_RATIO = 3

client_live.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)

# 🛠 Các hằng số lệnh



ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_STOP_MARKET = "STOP_MARKET"
ORDER_TYPE_TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

# 📡 WebSocket xử lý dữ liệu nến
def get_historical_data(symbol, interval, limit=90):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    response = requests.get(url)
    data = response.json()
    
    df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume", "_", "_", "_", "_", "_", "_"])
    df = df[["time", "open", "high", "low", "close", "volume"]].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df["MA89"] = df["close"].rolling(window=89).mean()
    return df

def on_message(ws, message):
    global df_candles
    try:
        data = json.loads(message)
        if "k" not in data:
            return  

        kline = data["k"]
        new_candle = {
            'time': pd.to_datetime(kline['t'], unit='ms'),
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v'])
        }

        new_candle_df = pd.DataFrame([new_candle])
        df_candles = pd.concat([df_candles, new_candle_df]).tail(100).reset_index(drop=True)
        df_candles["MA89"] = df_candles["close"].rolling(window=89).mean()
        
        signal = check_signal()
        if signal[0]:
            print(f"🔥 {signal[0]} | Entry: {signal[1]}, SL: {signal[2]}, TP: {signal[3]}")
    except Exception as e:
        print(f"❌ Lỗi WebSocket:", e)


def on_error(ws, error):
    print(f"❌ Lỗi WebSocket:", error)

def monitor_websocket():
    global ws
    while True:
        if ws and ws.sock and ws.sock.connected:
            print("✅ WebSocket kết nối OK...")
        else:
            print("⚠️ WebSocket bị mất kết nối! Restart...")
            restart_websocket()
        time.sleep(10)  # Kiểm tra mỗi 10 giây

def restart_websocket():
    global ws, ws_thread
    time.sleep(5)
    ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close)
    ws_thread = threading.Thread(target=ws.run_forever, daemon=True)
    ws_thread.start()

def on_open(ws):
    ws.send(json.dumps({
        "method": "SUBSCRIBE",
        "params": [f"{SYMBOL}@kline_{TIMEFRAME}"],
        "id": 1
    }))

def on_close(ws, close_status_code, close_msg):
    print("🔄 WebSocket đóng, khởi động lại...")
    restart_websocket()

ws_url = "wss://fstream.binance.com/ws"
restart_websocket()



# 📊 Kiểm tra tín hiệu giao dịch
# Khởi tạo DataFrame với dữ liệu lịch sử
df_candles = get_historical_data(SYMBOL, TIMEFRAME) 

def check_signal(df_candles):
    print("🔍 Đang kiểm tra tín hiệu...")
    if len(df_candles) < 90:
        print("⚠️ Không đủ dữ liệu MA89!")
        return None, None, None, None
    last_candle = df_candles.iloc[-2]
    prev_candle = df_candles.iloc[-3]
    ma89 = round(last_candle['MA89'], 4)
    if pd.isna(ma89):
        print("⚠️ MA89 chưa tính toán xong!")
        return None, None, None, None

    if prev_candle['close'] < prev_candle['open'] and last_candle['close'] > last_candle['open'] and last_candle['close'] > prev_candle['high'] and last_candle['close'] > ma89:
        print("✅ Xác nhận Engulfing tăng!")
        entry = last_candle['close']
        stop_loss = min(prev_candle['low'], last_candle['low'])

        distance = entry - stop_loss
        min_distance = entry * 0.005  # 0.5% của entry
        max_distance = entry * 0.01   # 1% của entry

        if distance < min_distance:
            stop_loss = entry - min_distance
        elif distance > max_distance:
            stop_loss = entry - max_distance
        else:
            stop_loss = min(prev_candle['low'], last_candle['low'])

        take_profit = entry + ((entry - stop_loss) * RR_RATIO)
        return "BUY", entry, stop_loss, take_profit
    
    elif prev_candle['close'] > prev_candle['open'] and last_candle['close'] < last_candle['open'] and last_candle['close'] < prev_candle['low'] and last_candle['close'] < ma89:
        print("✅ Xác nhận Engulfing giảm!")
        entry = last_candle['close']
        stop_loss = max(prev_candle['high'], last_candle['high'])

        distance = stop_loss - entry
        min_distance = entry * 0.005  # 0.5% của entry
        max_distance = entry * 0.01   # 1% của entry

        if distance < min_distance:
            stop_loss = entry + min_distance
        elif distance > max_distance:
            stop_loss = entry + max_distance
        else:
            stop_loss = max(prev_candle['high'], last_candle['high'])
        take_profit = entry - ((stop_loss - entry) * RR_RATIO)
        return "SELL", entry, stop_loss, take_profit
    print("⚠️ Không có tín hiệu giao dịch!")
    return None, None, None, None

# 📌 Tính số lượng lệnh
def get_precision(symbol):
    exchange_info = client_live.futures_exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':  # LOT_SIZE chứa stepSize
                    step_size = float(f['stepSize'])
                    return len(str(step_size).split('.')[1].rstrip('0')) if '.' in str(step_size) else 0
    return 0  # Trả về 0 nếu không tìm thấy stepSize

def round_quantity(quantity, precision):
    return round(quantity, precision)

def calculate_quantity(entry, stop_loss):
    risk_per_unit = abs(entry - stop_loss)
    if risk_per_unit == 0:
        return None
    
    quantity = RISK_AMOUNT / risk_per_unit
    precision = get_precision(SYMBOL)
    quantity = round_quantity(quantity, precision)
    return round(quantity, 2) if quantity > 0 else None

# Kiểm tra lệnh LIMIT
def is_limit_order(order_id, symbol):
    try:
        order_info = client_live.futures_get_order(symbol=symbol, orderId=order_id)
        
        # Kiểm tra loại lệnh
        if order_info and order_info['type'] == 'LIMIT':
            return True
        else:
            return False
    except Exception as e:
        print(f"⚠️ Lỗi kiểm tra lệnh LIMIT: {e}")
        return False

def cancel_existing_limit_orders():
    try:
        open_orders = client_live.futures_get_open_orders(symbol=SYMBOL)
        
        for order in open_orders:
            if order["type"] == "LIMIT":  # Chỉ hủy lệnh LIMIT
                client_live.futures_cancel_order(symbol=SYMBOL, orderId=order["orderId"])
                print(f"❌ Đã hủy lệnh LIMIT cũ: {order['orderId']}")
    
    except Exception as e:
        print(f"⚠️ Lỗi khi hủy lệnh LIMIT: {e}")

# 📌 Đặt lệnh Limit Order
def place_order(order_type, entry, stop_loss, take_profit):

    side = SIDE_BUY if order_type == "BUY" else SIDE_SELL
    opposite_side = SIDE_SELL if order_type == "BUY" else SIDE_BUY
    quantity = calculate_quantity(entry, stop_loss)

    if not quantity:
        print("⚠️ Không thể tính toán số lượng, bỏ qua lệnh!")
        return

     # Kiểm tra nếu đã có lệnh Limit đang chờ khớp
    try:
        # 🛑 Kiểm tra nếu đã có lệnh Limit tại cùng mức giá
        open_orders = client_live.futures_get_open_orders(symbol=SYMBOL)
        if any(float(o["price"]) == round(entry, 4) and o["side"] == side for o in open_orders):
            print(f"⚠️ Đã có lệnh Limit {side} tại {entry}, không đặt lệnh mới!")
            return
    except Exception as e:
        print(f"⚠️ Lỗi kiểm tra lệnh mở: {e}")
        return
    

    # Hủy lệnh limit cũ trước khi đặt lệnh mới
    cancel_existing_limit_orders()

    try:
        # Đặt lệnh LIMIT mới
        order = client_live.futures_create_order(
            symbol=SYMBOL,
            side=side,
            type=ORDER_TYPE_LIMIT,
            timeInForce="GTC",
            quantity=quantity,
            price=round(entry, 4)
        )
        order_id = order["orderId"]
        print(f"🟢 Đặt Limit Order {side} tại {entry} với số lượng: {quantity}")
    

        if wait_for_order_fill(order_id):
            # Kiểm tra lại vị thế sau khi lệnh mới khớp
            max_attempts = 5
            position_opened = False

            for attempt in range(max_attempts):
                time.sleep(1)  # Đợi 1 giây để Binance cập nhật
                positions = client_live.futures_position_information(symbol=SYMBOL)
                if any(float(pos["positionAmt"]) != 0 for pos in positions):
                    position_opened = True
                    break

            if position_opened:
                try:
                    sl_order = client_live.futures_create_order(
                        symbol=SYMBOL,
                        side=opposite_side,
                        type=ORDER_TYPE_STOP_MARKET,
                        quantity=quantity,
                        stopPrice=round(stop_loss, 4),
                        reduceOnly=True
                    )
                    tp_order = client_live.futures_create_order(
                        symbol=SYMBOL,
                        side=opposite_side,
                        type=ORDER_TYPE_TAKE_PROFIT_MARKET,
                        quantity=quantity,
                        stopPrice=round(take_profit, 4),
                        reduceOnly=True
                    )

                    print(f"✅ Đã đặt SL tại {stop_loss} và TP tại {take_profit}")
                    monitor_and_cancel(sl_order["orderId"], tp_order["orderId"])
                except Exception as e:
                    print("❌ Lỗi đặt SL/TP:", e)
            else:
                print("⚠️ Chưa có vị thế nào sau khi khớp lệnh!")

    except Exception as e:
        print("❌ Lỗi đặt lệnh:", e)

def wait_for_order_fill(order_id):
    print(f"⏳ Đang chờ LIMIT ORDER {order_id} khớp...")
    
    for _ in range(30):
        try:
            order_info = client_live.futures_get_order(symbol=SYMBOL, orderId=order_id)
            if order_info["status"] == "FILLED":
                print(f"✅ Lệnh {order_id} đã khớp!")
                return True
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Lỗi kiểm tra trạng thái lệnh: {e}")
            time.sleep(2)
    
    return False
    
def is_order_filled(order_id):
    for _ in range(5):  # Thử tối đa 5 lần
        try:
            order_info = client_live.futures_get_order(symbol=SYMBOL, orderId=order_id)
            
            if not order_info:
                print(f"⚠️ Lệnh {order_id} không tồn tại!")
                return False

            status = order_info["status"]
            print(f"🔍 Trạng thái lệnh {order_id}: {status}")

            if status in ["FILLED", "CANCELED", "EXPIRED"]:
                return True
            
            time.sleep(1)  # Chờ 1 giây rồi kiểm tra lại
            
        except BinanceAPIException as e:
            print(f"🚨 API bị từ chối: {e.message}")
            time.sleep(2)  # Chờ 2 giây rồi thử lại
        except Exception as e:
            print(f"⚠️ Lỗi kiểm tra trạng thái lệnh: {e}")
            time.sleep(1)
    
    return False  # Nếu thử 5 lần vẫn không lấy được trạng thái

# 🔄 Theo dõi và hủy lệnh SL/TP nếu cần
def monitor_and_cancel(sl_order_id, tp_order_id):
    while True:
        try:
            sl_filled = is_order_filled(sl_order_id)
            tp_filled = is_order_filled(tp_order_id)

            if sl_filled:
                print(f"🔴 Lệnh SL {sl_order_id} đã khớp! Hủy TP {tp_order_id}.")
                client_live.futures_cancel_order(symbol=SYMBOL, orderId=tp_order_id)
                return
            
            if tp_filled:
                print(f"🟢 Lệnh TP {tp_order_id} đã khớp! Hủy SL {sl_order_id}.")
                client_live.futures_cancel_order(symbol=SYMBOL, orderId=sl_order_id)
                return

            time.sleep(1)  # Kiểm tra mỗi giây
        except Exception as e:
            print(f"⚠️ Lỗi khi hủy SL/TP: {e}")
            time.sleep(1)

# 🔄 Vòng lặp giao dịch
def trading_loop():
    while True:
        try:
            positions = client_live.futures_position_information(symbol=SYMBOL)
            if not any(float(pos["positionAmt"]) != 0 for pos in positions):
                df_candles = get_historical_data(SYMBOL, TIMEFRAME) 
                signal, entry, stop_loss, take_profit = check_signal(df_candles)
                if signal:
                    place_order(signal, entry, stop_loss, take_profit)
            time.sleep(5)
        except Exception as e:
            print("❌ Lỗi vòng lặp giao dịch:", e)
            time.sleep(5)

trading_loop()