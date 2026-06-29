"""Quick smoke test for progressive disclosure."""
import sys
import types
sys.path.insert(0, '.')

# Stub out copium.__init__ to avoid heavy dependency chain
copium_mod = types.ModuleType('copium')
copium_mod.__path__ = ['copium']
sys.modules['copium'] = copium_mod
mcp_mod = types.ModuleType('copium.mcp_proxy')
mcp_mod.__path__ = ['copium/mcp_proxy']
sys.modules['copium.mcp_proxy'] = mcp_mod

from copium.mcp_proxy.progressive_disclosure.config import ProgressiveDisclosureConfig
from copium.mcp_proxy.progressive_disclosure.registry import ToolSchemaRegistry
from copium.mcp_proxy.progressive_disclosure.eager_policy import EagerLoadingPolicy
from copium.mcp_proxy.progressive_disclosure.search import BM25Index
from copium.mcp_proxy.progressive_disclosure.engine import ProgressiveDisclosureEngine
from copium.mcp_proxy.progressive_disclosure.interceptor import ProgressiveDisclosureInterceptor

tools = []
for i in range(20):
    tools.append({
        'name': 'tool_%d' % i,
        'description': 'Tool number %d for testing' % i,
        'input_schema': {
            'type': 'object',
            'properties': {'x': {'type': 'string'}},
        },
    })

config = ProgressiveDisclosureConfig(min_tools_for_disclosure=5, eager_load_max=4)
interceptor = ProgressiveDisclosureInterceptor(config)
body = {'tools': tools, 'messages': [{'role': 'user', 'content': 'hello'}], 'system': 'test'}
result = interceptor.intercept_request(body)

assert len(result['tools']) < len(tools), "Should reduce tool count"
metrics = interceptor.get_metrics()
assert metrics['active'] is True
assert metrics['savings_pct'] > 0

find_result = interceptor.intercept_tool_call('copium_find_tool', {'query': 'tool 5'})
assert find_result is not None
assert find_result['type'] == 'text'

call_result = interceptor.intercept_tool_call('copium_call_tool', {'tool_name': 'tool_5', 'arguments': {'x': 'hi'}})
assert call_result is not None
assert call_result['type'] == 'dispatch'

print('All smoke tests PASSED')
print('Original: %d tools -> Sent: %d tools' % (len(tools), len(result['tools'])))
print('Savings: %.1f%%' % metrics['savings_pct'])
