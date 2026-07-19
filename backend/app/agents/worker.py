# Agent 计算 Worker：独立进程，监听 gRPC 请求，执行 LLM 调用
# 启动方式：python -m app.agents.worker --port 50051
# 可部署在多台机器上实现横向扩展

import argparse
import asyncio
import contextlib

from app.agents.compute import LocalAgentCompute
from app.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger("agents.worker")


async def serve(port: int = 50051) -> None:
    """启动 Worker 服务"""
    logger.info("Agent Worker 启动中，端口 %d", port)

    # TODO: 实现 gRPC 服务端
    # from grpc import aio as grpc_aio
    # import agent_compute_pb2_grpc
    #
    # class AgentComputeServicer(agent_compute_pb2_grpc.AgentComputeServiceServicer):
    #     def __init__(self):
    #         self._compute = LocalAgentCompute()
    #
    #     async def Think(self, request, context):
    #         # 从 gRPC 请求转 ThinkRequest
    #         req = ThinkRequest(
    #             request_id=request.request_id,
    #             meeting_id=request.meeting_id,
    #             ...
    #         )
    #         # 执行思考
    #         resp = await self._compute.think(req)
    #         # 转 gRPC 响应
    #         return agent_compute_pb2.ThinkResponse(
    #             success=resp.success,
    #             result_json=json.dumps(resp.result, ensure_ascii=False),
    #             ...
    #         )
    #
    # server = grpc_aio.server()
    # agent_compute_pb2_grpc.add_AgentComputeServiceServicer_to_server(
    #     AgentComputeServicer(), server
    # )
    # server.add_insecure_port(f"[::]:{port}")
    # await server.start()
    # logger.info("Worker 监听 %d，等待请求...", port)
    # await server.wait_for_termination()

    # 当前 stub：直接运行本地计算，验证接口
    logger.info("Worker stub 模式：使用 LocalAgentCompute")
    LocalAgentCompute()
    logger.info("Worker 就绪（stub），按 Ctrl+C 退出")
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.Event().wait()  # 永久等待


def main():
    parser = argparse.ArgumentParser(description="Conclave Agent Worker")
    parser.add_argument("--port", type=int, default=50051, help="gRPC 监听端口")
    args = parser.parse_args()
    asyncio.run(serve(args.port))


if __name__ == "__main__":
    main()
