"""DeepSeek 调用封装：知识点提取 / 脚本生成 / 报错修复。"""
import json
import re

from openai import OpenAI

from .config import (DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, MAX_COURSETEXT_CHARS,
                     get_api_key)
from . import prompt
from .domains import DEFAULT_DOMAIN, get_pack


class LLMError(Exception):
    pass


class NoMathContentError(LLMError):
    """文档里没有该学科可可视化的知识点（可能文档内容与该学科无关）。"""


def _client() -> OpenAI:
    key = get_api_key()
    if not key:
        raise LLMError(
            "未找到 DeepSeek API Key。请设置环境变量 DEEPSEEK_API_KEY，"
            "或在 mathviz/.env 中写入 DEEPSEEK_API_KEY=sk-..."
        )
    return OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL)


def chat(system: str, user: str, temperature: float = 0.7, max_tokens: int = 4096) -> str:
    client = _client()
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:  # 网络错误、鉴权错误等统一包装
        raise LLMError(f"DeepSeek 调用失败: {e}") from e
    content = resp.choices[0].message.content
    if not content:
        raise LLMError("DeepSeek 返回了空内容")
    return content.strip()


def chat_messages(system: str, messages: list[dict],
                  temperature: float = 0.7, max_tokens: int = 4096) -> str:
    """多轮对话版 chat：messages = [{"role": "user"/"assistant", "content": ...}]。"""
    client = _client()
    try:
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        raise LLMError(f"DeepSeek 调用失败: {e}") from e
    content = resp.choices[0].message.content
    if not content:
        raise LLMError("DeepSeek 返回了空内容")
    return content.strip()


def strip_code_fence(text: str) -> str:
    """去掉 markdown 围栏与首尾空白；容忍模型偶尔不听话。"""
    text = text.strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip()


_CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)


def force_scene_name(code: str, scene_name: str) -> str:
    """确保脚本里那个 Scene 子类就叫 scene_name。

    AI 时不时自作主张起名（DemoScene / MainScene / 随手一个 X），而我们是按
    scene_name 去调 manim 的 —— 名字对不上就会被判"未找到 Scene 类"，
    白白触发一轮自修复（多一次 API 调用 + 多等几十秒）。
    脚本通常只有一个类，直接改名最省事；类不止一个时不动手，交给静态检查报错。
    """
    if not code or not scene_name:
        return code
    if re.search(rf"^class\s+{re.escape(scene_name)}\s*\(", code, re.M):
        return code
    matches = list(_CLASS_RE.finditer(code))
    scene_classes = [m for m in matches if "Scene" in m.group(2)]
    if len(matches) != 1 or len(scene_classes) != 1:
        return code
    m = scene_classes[0]
    return code[:m.start(1)] + scene_name + code[m.end(1):]


def _parse_json_array(text: str, subject: str = "数学") -> list:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            raise LLMError("知识点提取结果不是合法 JSON") from exc
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc2:
            # 抠出来的片段也可能是坏的（AI 把两个数组拼在一起之类），
            # 一样要转成 LLMError，别让裸 JSONDecodeError 冒到界面上
            raise LLMError("知识点提取结果不是合法 JSON") from exc2
    if not isinstance(data, list):
        raise LLMError("知识点提取结果不是数组")
    points = []
    for item in data:
        if isinstance(item, dict) and item.get("title"):
            points.append({
                "title": str(item["title"]),
                "description": str(item.get("description", "")),
                "level": str(item.get("level", "")),
            })
    if not points:
        raise NoMathContentError(
            f"没有从中提取到{subject}知识点。可能这份文档不属于「{subject}」范畴，"
            f"或缺少可可视化的{subject}对象——仅仅含有数字和百分比是不够的。"
            f"请换一份{subject}课件再试。"
        )
    return points


def extract_points(course_text: str, domain: str = DEFAULT_DOMAIN) -> list[dict]:
    """课件文本 -> [{title, description, level}, ...]"""
    pack = get_pack(domain)
    text = course_text[:MAX_COURSETEXT_CHARS]
    raw = chat(pack.extract_system, text, temperature=0.3, max_tokens=3000)
    return _parse_json_array(raw, subject=pack.subject)


def plan_content(history: list[dict], course_text: str,
                 domain: str = DEFAULT_DOMAIN) -> str:
    """对话式策划：根据课件（可为空）与对话历史，给出/更新"呈现清单"。

    history 不含刚发出的这条消息以外的系统消息；调用方把用户最新消息
    放在 history 末尾一起传进来。
    """
    pack = get_pack(domain)
    # 只保留 user/assistant 消息，每条截断，总条数封顶，防上下文爆炸
    trimmed = []
    for m in history[-12:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            trimmed.append({"role": m["role"],
                            "content": str(m["content"])[:1500]})
    latest = ""
    if trimmed and trimmed[-1]["role"] == "user":
        latest = trimmed.pop()["content"]
    system = pack.plan_system or prompt.PLAN_SYSTEM
    user = prompt.PLAN_USER_TEMPLATE.format(
        context=course_text[:4000] or "（无课件，请围绕用户想学的知识点直接策划）",
        history="\n".join(
            f"{'用户' if m['role'] == 'user' else '策划'}：{m['content']}"
            for m in trimmed) or "（无）",
        message=latest or "（请给出这份内容的呈现清单）",
    )
    return chat(system, user, temperature=0.5, max_tokens=2000)


_TOPIC_FALLBACK = "自定义动画"
_TOPIC_MAX_CHARS = 20


def _clean_topic(raw: str) -> str:
    """把模型返回的标题收拾干净：去围栏、去引号书名号、去句末标点、限长。"""
    text = strip_code_fence(raw).strip()
    for ch in ("《", "》", "「", "」", "【", "】", "\"", "'", "`", "*"):
        text = text.replace(ch, "")
    text = text.splitlines()[0].strip() if text else ""
    text = text.strip("。，、；：！？.,;:!? \t-—_")
    # 模型偶尔仍会带一句说明（"知识点：导数的定义"），取冒号后那段
    for sep in ("：", ":", "->", "→"):
        if sep in text and len(text.split(sep)[-1].strip()) >= 2:
            text = text.split(sep)[-1].strip()
            break
    if not text:
        return _TOPIC_FALLBACK
    return text[:_TOPIC_MAX_CHARS]


def summarize_topic(user_text: str, domain: str = DEFAULT_DOMAIN) -> str:
    """把用户口语化的需求提炼成一个简短知识点名（用于脚本与成片命名）。

    失败时向上抛 LLMError，调用方自行决定退回策略 —— 标题不该阻断生成流程。
    """
    pack = get_pack(domain)
    raw = chat(prompt.TOPIC_SYSTEM + f"\n学科：{pack.subject}。",
               prompt.TOPIC_USER_TEMPLATE.format(text=(user_text or "")[:1500]),
               temperature=0.2, max_tokens=64)
    return _clean_topic(raw)


def generate_script(title: str, description: str, level: str,
                    context: str, scene_name: str,
                    domain: str = DEFAULT_DOMAIN, plan: str = "") -> str:
    pack = get_pack(domain)
    user = prompt.GENERATE_USER_TEMPLATE.format(
        title=title, description=description, level=level or "未指定",
        plan=plan.strip() or "（无 —— 请自行安排合理的教学叙事结构）",
        context=context[:4000] or "（无）", scene_name=scene_name,
    )
    return strip_code_fence(chat(pack.generate_system, user, temperature=0.6))


def fix_script(code: str, error_tail: str, scene_name: str,
               domain: str = DEFAULT_DOMAIN) -> str:
    pack = get_pack(domain)
    user = prompt.FIX_USER_TEMPLATE.format(
        scene_name=scene_name, code=code, error_tail=error_tail[-3500:]
    )
    return strip_code_fence(chat(pack.fix_system, user, temperature=0.2))


def revise_script(code: str, request: str, scene_name: str,
                  domain: str = DEFAULT_DOMAIN) -> str:
    """代码修改模式：按用户的画面效果要求直接改现有脚本（不重新策划清单）。"""
    user = prompt.REVISE_USER_TEMPLATE.format(
        scene_name=scene_name, code=code, request=request
    )
    return strip_code_fence(chat(prompt.REVISE_SYSTEM, user, temperature=0.4))
