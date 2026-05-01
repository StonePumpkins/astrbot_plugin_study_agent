import httpx
import random
import json
import os
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_study_agent", "YourName", "多Agent学习助手", "1.0.0")
class StudyAgent(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # LM Studio 的本地地址，如果你的端口号不同就改这里
        plugin_dir = os.path.dirname(__file__)
        self.motto_file = os.path.join(plugin_dir, "motto.json")
        # 这里两句是导入 motto.json并且把它的路径保存在 self.motto_file 里，后面就可以通过 self.motto_file 来访问这个文件了
        self.LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

    # 基础指令：测试插件是否存活
    @filter.command("ping")
    async def ping(self, event: AstrMessageEvent):
        yield event.plain_result("🏓 Pong！插件运行正常。")

    # 核心指令：接上本地大脑
    @filter.command("ask")
    async def ask(self, event: AstrMessageEvent):
        # 1. 拿到用户的问题
        msg = event.message_str.strip()
        question = msg.replace("/ask", "", 1).strip()
        if not question:
            yield event.plain_result("用法：/ask <你的问题>")
            return

        # 2. 先告诉用户“我开始想了”
        yield event.plain_result("🤔 正在思考，请稍候...")

        # 3. 构造发送给 LM Studio 的数据包
        payload = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": "你是一个乐于助人的智能助手。"},
                {"role": "user", "content": question}
            ],
            "temperature": 2 # 这里调灵活度 0～2
        }
        # 4. 发送请求，并处理结果或报错
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self.LM_STUDIO_URL, json=payload)
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
                yield event.plain_result(answer)
        except httpx.HTTPError as e:
            logger.error(f"LM Studio连接失败: {e}")
            yield event.plain_result("😵 连接本地大脑失败，请确认LM Studio已开启。")
        except Exception as e:
            logger.error(f"未知错误: {e}")
            yield event.plain_result(f"😵 出错了：{str(e)}")

    @filter.command("motto") #随机抽取 motto功能（未完成）
    async def motto(self,event:AstrMessageEvent):
        try:
            with open(self.motto_file, "r", encoding="utf-8") as f:
                mottos = json.load(f)
            motto = random.sample(mottos,100)
            yield event.plain_result(motto)
        except Exception as e:
            logger.error(f"读取motto失败: {e}")
            yield event.plain_result("😵 无法获取格言，请稍后再试。")


# 今天5.1先到这了 目前motto随机抽取功能还没好，motto.json文件今天搞好了，明天需要写async def motto里的随机抽取功能和输出
