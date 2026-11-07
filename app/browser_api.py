"""Use the device-local endpoints in the browser's dedicated Python worker."""
from pathlib import Path
import threading

from . import mobile_api
from .domain import DomainError
from .offline_runtime import prepare_runtime


class BrowserRuntime(mobile_api.LocalRuntime):
    def __init__(self, data_dir, knowledge_dir):
        self.data_dir = Path(data_dir).resolve()
        self.pack = prepare_runtime(self.data_dir, Path(knowledge_dir))
        self.guard = threading.RLock()

    def handle(self, method, target, body=None):
        if isinstance(target, str) and target.startswith('/model/'):
            raise DomainError(501, '云模型请使用电脑本机版')
        status, result = super().handle(method, target, body)
        if 'platform' in result:
            result['platform'] = 'browser'
        return status, result


def initialize(data_dir, knowledge_dir):
    mobile_api._runtime = BrowserRuntime(data_dir, knowledge_dir)


dispatch = mobile_api.dispatch
