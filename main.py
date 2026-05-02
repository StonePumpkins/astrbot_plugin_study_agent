import httpx
import random
import json
import os
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# ===== Agent 配置注册表（未来扩展点）=====
AGENT_REGISTRY = {
    "examiner": {
        "name": "审题员",
        "system_prompt": (
            "你是一位严谨的审题专家。你的任务是从题目中提取关键信息，"
            "不解答题目，只输出：\n"
            "1. 已知条件（逐条列出）\n"
            "2. 求解目标\n"
            "3. 隐藏条件或易错点"
        ),
        "temperature": 0.3
    },
    "feynman": {
        "name": "费曼讲师",
        "system_prompt": (
            "你是理查德·费曼。你坚信任何知识都能用最简单的方式讲清楚。\n"
            "讲题规则：\n"
            "1. 先打一个生活化的比方建立直觉\n"
            "2. 再讲原理，但禁用术语，除非先用类比解释\n"
            "3. 最后用一句话总结核心思想"
        ),
        "temperature": 0.7
    },
    "analyzer": {
        "name": "剖析员",
        "system_prompt": (
            "你是一位深度思考者。你会收到题目的审题分析，"
            "你的任务是追问：这道题在考哪个核心概念？为什么这些条件能导出这种解法？"
            "请用清晰的语言阐述背后的学科原理和逻辑链，尽可能避免术语，若用术语必须解释。"
        ),
        "temperature": 0.3
    },
    "quiz_maker": {
        "name": "出题人",
        "system_prompt": (
            "你是一位经验丰富的出题老师。你会收到完整的教学材料（审题、原理、讲解），"
            "请出一道同类型的变式题，考察学习者是否真正理解。"
            "题目应稍有变化但核心知识点相同，并给出简略的解答提示。"
        ),
        "temperature": 0.7
    }
}

PIPELINES = {
    "teach": ["examiner", "analyzer", "feynman", "quiz_maker"]
}

@register("astrbot_plugin_study_agent", "YourName", "多Agent学习助手", "1.0.0")
class StudyAgent(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        plugin_dir = os.path.dirname(__file__)
        self.motto_file = os.path.join(plugin_dir, "motto.json")
        self.LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

    # ─── 公共工具方法 ─────────────────────────────────

    def _extract_question(self, event: AstrMessageEvent, prefix: str = "/ask") -> str:
        """从消息中提取用户问题，去掉指令前缀并清理空格"""
        msg = event.message_str.strip()
        return msg.replace(prefix, "", 1).strip()

    async def _call_lm_studio(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7
    ) -> str:
        """调用本地大模型，返回模型回复文本"""
        payload = {
            "model": "local-model",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(self.LM_STUDIO_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            message = result["choices"][0]["message"]
            content = message.get("content", "")
            reasoning = message.get("reasoning_content", "")
            # 优先返回 content，如果为空则返回 reasoning
            return content if content else reasoning

    async def _run_pipeline(self, pipeline_name: str, user_input: str) -> str:
        """执行指定流水线，返回最后一步的输出"""
        agent_names = PIPELINES.get(pipeline_name, [])
        current_input = user_input

        for agent_name in agent_names:
            agent = AGENT_REGISTRY[agent_name]
            # yield None  # 占位，方便未来在这里加入中间步骤的回调
            current_input = await self._call_lm_studio(
                system_prompt=agent["system_prompt"],
                user_message=current_input,
                temperature=agent.get("temperature", 0.7)
            )
        return current_input

    # ─── 基础指令 ─────────────────────────────────────

    @filter.command("ping")
    async def ping(self, event: AstrMessageEvent):
        yield event.plain_result("🏓 Pong！插件运行正常。")

    @filter.command("motto")
    async def motto(self, event: AstrMessageEvent):
        try:
            with open(self.motto_file, "r", encoding="utf-8") as f:
                mottos = json.load(f)
            motto = random.choice(mottos)
            if isinstance(motto, str):
                yield event.plain_result(f"📜 {motto}")
            else:
                yield event.plain_result(
                    f"📜 {motto['content']}\n—— {motto.get('author', '佚名')}"
                )
        except Exception as e:
            logger.error(f"读取motto失败: {e}")
            yield event.plain_result("😵 无法获取格言，请稍后再试。")

    # ─── AI 指令 ──────────────────────────────────────

    @filter.command("ask")
    async def ask(self, event: AstrMessageEvent):
        question = self._extract_question(event, "/ask")
        if not question:
            yield event.plain_result("用法：/ask <你的问题>")
            return

        yield event.plain_result("🤔 正在思考，请稍候...")

        try:
            answer = await self._call_lm_studio(
                system_prompt="你是一个乐于助人的智能助手。",
                user_message=question
            )
            yield event.plain_result(answer)
        except httpx.HTTPError as e:
            logger.error(f"LM Studio连接失败: {e}")
            yield event.plain_result("😵 连接本地大脑失败，请确认LM Studio已开启。")
        except Exception as e:
            logger.error(f"未知错误: {e}")
            yield event.plain_result(f"😵 出错了：{str(e)}")

    @filter.command("teach")
    async def teach(self, event: AstrMessageEvent):
        """多Agent教学流水线：审题员 to 剖析员 to 费曼讲师 to 出题人"""
        question = self._extract_question(event, "/teach")
        if not question:
            yield event.plain_result("用法：/teach <题目>")
            return

        yield event.plain_result("🔍 正在拆解题目，请稍候...")

        try:
                # 串行调用四个 Agent
            exam = await self._call_lm_studio(
                system_prompt=AGENT_REGISTRY["examiner"]["system_prompt"],
                user_message=question,
                temperature=AGENT_REGISTRY["examiner"]["temperature"]
            )
            analyze = await self._call_lm_studio(
                system_prompt=AGENT_REGISTRY["analyzer"]["system_prompt"],
                user_message=f"题目：{question}\n审题分析：{exam}",
                temperature=AGENT_REGISTRY["analyzer"]["temperature"]
            )
            teach = await self._call_lm_studio(
                system_prompt=AGENT_REGISTRY["feynman"]["system_prompt"],
                user_message=f"题目：{question}\n审题分析：{exam}\n原理剖析：{analyze}",
                temperature=AGENT_REGISTRY["feynman"]["temperature"],
            )
            quiz = await self._call_lm_studio(
                system_prompt=AGENT_REGISTRY["quiz_maker"]["system_prompt"],
                user_message=f"原题：{question}\n审题：{exam}\n原理：{analyze}\n讲解：{teach}",
                temperature=AGENT_REGISTRY["quiz_maker"]["temperature"]
            )

            yield event.plain_result(
                f"📋 审题分析：\n{exam}\n\n"
                f"🧠 原理剖析：\n{analyze}\n\n"
                f"💡 费曼讲解：\n{teach}\n\n"
                f"📝 变式练习：\n{quiz}"
            )

        except httpx.HTTPError as e:
            logger.error(f"LM Studio连接失败: {e}")
            yield event.plain_result("😵 连接本地大脑失败，请确认LM Studio已开启。")
        except Exception as e:
            logger.error(f"未知错误: {e}")
            yield event.plain_result(f"😵 出错了：{str(e)}")