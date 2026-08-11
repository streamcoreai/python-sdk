# streamcore (Python)

[English](./README.md) | **简体中文**

Python SDK，通过 WebRTC + WHIP 连接 [streamcore](https://github.com/streamcore/streamcore-server) 服务端，底层由 [aiortc](https://github.com/aiortc/aiortc) 驱动。

## 环境要求

- **Python 3.10+**

## 安装

```bash
pip install streamcore
```

或者从源码安装：

```bash
cd python-sdk
pip install -e .
```

## 快速开始

```python
import asyncio
import numpy as np
import streamcore


async def main():
    def on_transcript(entry, all_entries):
        print(f"[{entry.role}] {entry.text}")

    client = streamcore.Client(
        config=streamcore.Config(whip_endpoint="http://localhost:8080/whip"),
        events=streamcore.EventHandler(
            on_transcript=on_transcript,
            on_error=lambda err: print(f"Error: {err}"),
        ),
    )

    await client.connect()

    # Send a 20 ms frame of silence
    pcm = np.zeros(streamcore.FRAME_SIZE, dtype=np.int16)
    await client.send_pcm(pcm)

    # Receive decoded audio from the agent
    audio = await client.recv_pcm()  # numpy int16 array

    await client.disconnect()


asyncio.run(main())
```

## API

### `Client(config?, events?)`

创建一个新的语音智能体客户端。

#### `Config`

| 字段           | 类型         | 默认值                        | 说明                 |
| --------------- | ------------ | ------------------------------ | --------------------------- |
| `whip_endpoint` | `str`        | `"http://localhost:8080/whip"` | WHIP 信令端点 URL |
| `token`         | `str`        | `""`                           | 在 WHIP 请求中以 `Authorization: Bearer` 发送的 JWT |
| `token_url`     | `str`        | `""`                           | token 端点；设置后每次连接前都会取一次 JWT（优先于 `token`） |
| `api_key`       | `str`        | `""`                           | 从 `token_url` 取 token 时以 `Authorization: Bearer` 发送 |
| `ice_servers`   | `list[str]`  | `["stun:stun.l.google.com:19302"]` | ICE 服务器 URL        |

#### `EventHandler`

所有回调都是可选的。

| 回调                 | 签名                                                       | 说明                           |
| ------------------------ | --------------------------------------------------------------- | ------------------------------------- |
| `on_status_change`       | `(status: ConnectionStatus) -> None`                            | 连接状态变化时触发  |
| `on_transcript`          | `(entry: TranscriptEntry, all: list[TranscriptEntry]) -> None`  | 有新的或更新的转写时触发    |
| `on_agent_state_change`  | `(state: AgentState) -> None`                                   | 智能体开始聆听、思考或说话时触发 |
| `on_timing`              | `(event: TimingEvent) -> None`                                  | 携带服务端流水线耗时信息 |
| `on_error`               | `(error: Exception) -> None`                                    | 连接或服务端错误时触发  |
| `on_data_channel_message`| `(msg: DataChannelMessage) -> None`                             | 每条原始 DataChannel 消息都会触发        |

#### 方法

| 方法                          | 说明                                                  |
| ------------------------------- | ------------------------------------------------------------ |
| `await client.connect(track?)`  | 通过 WHIP 连接。可选传入一个 aiortc 音频 track。     |
| `await client.disconnect()`     | 拆除连接并释放资源。                     |
| `await client.send_pcm(pcm)`   | 向智能体发送 numpy int16 PCM 缓冲（单声道 48 kHz）。   |
| `await client.recv_pcm()`      | 以 numpy int16 数组接收解码后的 PCM 音频。            |
| `client.status`                 | 当前 `ConnectionStatus`。                                  |
| `client.transcript`             | 当前对话，类型为 `list[TranscriptEntry]`。             |
| `client.remote_track`           | 来自智能体的入站音频 track（connect 之后可用）。|

#### 音频常量

| 常量      | 值    | 说明                      |
| ------------- | -------- | -------------------------------- |
| `SAMPLE_RATE` | `48000`  | 音频采样率（Hz）          |
| `CHANNELS`    | `1`      | 声道数（单声道）        |
| `FRAME_SIZE`  | `960`    | 每 20 ms 帧的采样点数          |

## 音频 I/O

SDK 内部处理 aiortc 的 track 管理、`av.AudioFrame` 构造和重采样。调用方只需要处理 numpy int16 数组形式的原始 PCM 数据：

```python
# Send microphone audio (960 samples = 20 ms at 48 kHz)
await client.send_pcm(pcm_int16)

# Receive agent audio
audio = await client.recv_pcm()
```

如果你需要直接访问 track（例如自定义 aiortc 流水线），可通过 `client.connect(user_track=my_track)` 传入自己的 `AudioStreamTrack`。

## 依赖

| 包  | 用途                        |
| -------- | ------------------------------ |
| `aiortc` | WebRTC 协议栈                   |
| `aiohttp`| 用于 WHIP 信令的 HTTP 客户端 |
| `av`     | 音频帧编解码  |
| `numpy`  | PCM 音频缓冲             |

## 许可证

Apache-2.0
