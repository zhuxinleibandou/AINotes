from backend.codex import generate
from backend.models import VisualFrame
print(generate('仅返回描述为“连接正常”、visible_text为空、caveats为空的JSON。不调用工具。', VisualFrame, lambda:False))
