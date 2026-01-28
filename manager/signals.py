import json
import logging
import hmac
import hashlib
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional, Dict
from dotenv import load_dotenv

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class MacroHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        secret = os.getenv('WEBHOOK_PASSPHRASE', '')
        if secret:
            expected_sig = hmac.new(secret.encode(), post_data, hashlib.sha256).hexdigest()
            received_sig = self.headers.get('X-TV-Signature', '')
            if received_sig and received_sig != expected_sig:
                logger.warning("Invalid webhook signature received")
                self.send_response(401)
                self.end_headers()
                return
        try:
            data = json.loads(post_data.decode('utf-8'))
            logger.info(f"Received signal: {data}")
            if hasattr(self.server, 'signal_callback') and callable(self.server.signal_callback):
                self.server.signal_callback(data)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'received'}).encode())
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            self.send_response(400)
            self.end_headers()
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            self.send_response(500)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass

class SignalServer:
    def __init__(self, macro_callback: Callable, abot_callback: Optional[Callable] = None):
        self.macro_callback = macro_callback
        self.abot_callback = abot_callback
        self.port = int(os.getenv('WEBHOOK_PORT', 8090))
        self.server = None
        self.server_thread = None
        logger.info(f"Signal Server initialized on port {self.port}")

    def _handle_signal(self, data: Dict):
        signal_type = data.get('type', '').upper()
        if signal_type == 'MACRO' or 'mode' in data:
            mode = data.get('mode', data.get('action', 'BTC')).upper()
            if mode in ['BTC', 'GOLD']:
                logger.info(f"MACRO SIGNAL: Switching to {mode} MODE")
                if self.macro_callback:
                    self.macro_callback(mode)
        elif signal_type == 'SNIPER' or 'coin' in data:
            action = data.get('action', '').upper()
            coin = data.get('coin', data.get('symbol', '')).upper()
            if action in ['BUY', 'SELL'] and coin:
                logger.info(f"SNIPER SIGNAL: {action} {coin}")
                if self.abot_callback:
                    self.abot_callback(action, coin, data)

    def start(self):
        try:
            self.server = HTTPServer(('0.0.0.0', self.port), MacroHandler)
            self.server.signal_callback = self._handle_signal
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            logger.info(f"Signal Server listening on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start Signal Server: {e}")
            raise

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("Signal Server stopped")