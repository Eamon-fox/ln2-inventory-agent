# DeepSeek 深度思考模式 API 说明

更新时间：2026-02-13

## 核心要点

**只需要发送 `deepseek-chat` 模型，加 `thinking` 参数控制即可。**

API 会自动根据 `thinking` 参数选择合适的模型（返回时显示为 `deepseek-reasoner`）。

## 接入建议

### 请求体参数控制

- 模型使用 `deepseek-chat`
- 通过 `thinking` 参数控制思考模式：
  - `true` → 请求体加 `thinking: {"type": "enabled"}`
  - `false/空` → 不加这个字段

### 思考内容展示策略

- **没有收到思考内容时隐藏**：以 `reasoning_content`（或流式 `reasoning_content`）是否存在为判断条件
- **思考内容不单独分区**：直接作为 Agent 回复前半段连续渲染，不增加额外间距或卡片
- **仅做颜色区分**：思考内容使用灰色文字，正式回答保持默认颜色

## 非流式 API 示例

请求体：

```json
{
  "model": "deepseek-chat",
  "messages": [{"role": "user", "content": "深度学习的核心是什么？"}],
  "max_tokens": 256,
  "thinking": {"type": "enabled"}
}
```

返回：

```json
{
  "id": "xxx",
  "object": "chat.completion",
  "model": "deepseek-reasoner",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "深度学习的核心是...",
        "reasoning_content": "...（内部推理链）"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 13,
    "completion_tokens": 150,
    "total_tokens": 163,
    "completion_tokens_details": {
      "reasoning_tokens": 86
    }
  }
}
```

> 注意：传入 `thinking` 参数后，API 实际返回的模型是 `deepseek-reasoner`。

## 流式 API 示例

请求体：

```json
{
  "model": "deepseek-chat",
  "messages": [{"role": "user", "content": "你好"}],
  "max_tokens": 256,
  "stream": true,
  "thinking": {"type": "enabled"}
}
```

返回（每行以 `data:` 开头）：

```
data: {"delta":{"role":"assistant","content":null,"reasoning_content":""}}
data: {"delta":{"content":null,"reasoning_content":"哦"}}
...
data: {"delta":{"content":"你好","reasoning_content":null}}
data: {"delta":{"content":"","reasoning_content":null},"finish_reason":"stop","usage":{"completion_tokens_details":{"reasoning_tokens":76}}}
data: [DONE]
```

关键点：
- 流式每行以 `data:` 开头
- `delta` 里可同时看到 `reasoning_content` 与 `content`
- 思考内容先返回在 `reasoning_content`，正式回答后返回在 `content`
- 最后一条 chunk 携带 `usage`，并以 `data: [DONE]` 结束
