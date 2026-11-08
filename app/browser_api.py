"""Use the device-local endpoints in the browser's dedicated Python worker."""
from pathlib import Path
import threading

from . import mobile_api
from .browser_models import BrowserModels
from .offline_runtime import prepare_runtime


class BrowserRuntime(mobile_api.LocalRuntime):
    def __init__(self, data_dir, knowledge_dir):
        self.data_dir = Path(data_dir).resolve()
        self.pack = prepare_runtime(self.data_dir, Path(knowledge_dir))
        self.models = BrowserModels(self.data_dir)
        self.guard = threading.RLock()

    def handle(self, method, target, body=None):
        status, result = super().handle(method, target, body)
        if 'platform' in result:
            result['platform'] = 'browser'
        return status, result


def initialize(data_dir, knowledge_dir):
    mobile_api._runtime = BrowserRuntime(data_dir, knowledge_dir)


dispatch = mobile_api.dispatch


def take_requests():
    return mobile_api._runtime.models.take_requests()


def complete_request(request_id, response):
    mobile_api._runtime.models.complete_request(request_id, response)


def fail_request(request_id, error):
    mobile_api._runtime.models.fail_request(request_id, error)


def pending_request_ids():
    return mobile_api._runtime.models.pending_request_ids()


def checkpoint():
    return mobile_api._runtime.models.checkpoint()


def restore_checkpoint(value):
    mobile_api._runtime.models.restore_checkpoint(value)
