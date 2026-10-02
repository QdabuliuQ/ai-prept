"""SCORE_VL helpers — random theme / style intent."""

from __future__ import annotations

import os
import random
import time
from typing import Any

import httpx

from config import load_env


def resolve_score_vl() -> dict[str, str]:
    load_env()
    base = (
        os.environ.get("SCORE_VL_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    model = os.environ.get("SCORE_VL_MODEL") or "qwen-vl-max"
    api_key = (
        os.environ.get("SCORE_VL_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or (os.environ.get("SCORE_VL_API_KEYS") or "").split(",")[0].strip()
    )
    if not api_key:
        raise RuntimeError(
            "未配置 SCORE_VL / DashScope Key。请在 .env.local 设置 SCORE_VL_API_KEY 或 DASHSCOPE_API_KEY。"
        )
    return {"baseUrl": base, "model": model, "apiKey": api_key}


def _chat(system: str, user: str, *, temperature: float = 1.2, max_tokens: int = 220) -> dict[str, str]:
    cfg = resolve_score_vl()
    url = f"{cfg['baseUrl']}/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        res = client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['apiKey']}",
            },
            json={
                "model": cfg["model"],
                "temperature": temperature,
                "top_p": 0.95,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        res.raise_for_status()
        data = res.json()
    text = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    if text.startswith("```"):
        text = text.replace("```", "").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    text = text.strip().strip('"「『」』')
    return {"text": text, "model": cfg["model"]}


# 本地抽签拉开领域，避免模型反复落到「智慧城市 / 智能交通」默认套路
_THEME_DOMAINS: tuple[str, ...] = (
    # 消费与产业
    "餐饮与本地生活",
    "文旅景区运营",
    "教育培训机构",
    "医疗健康与康养",
    "体育赛事与运动品牌",
    "影视文娱与演出",
    "零售电商与新品",
    "农业与食品溯源",
    "制造业与工厂班组",
    "能源与环保公益",
    "金融理财（非科技口号）",
    "房产与家居生活",
    "母婴亲子",
    "宠物经济",
    "美妆个护",
    "游戏与二次元社群",
    "出版与知识付费",
    "非营利与社会公益",
    "传统手工艺与非遗",
    "职场软技能",
    "科研科普（具体学科）",
    "法律与合规",
    "人力资源与雇主品牌",
    "婚礼与人生仪式",
    # 机关 / 校园 / 组织生活
    "机关单位党建",
    "企业党支部学习",
    "高校学生党建",
    "中小学班级建设",
    "大学班级团日",
    "企业团建与部门协作",
    "工会职工活动",
    "社区网格服务",
    "村镇文明实践",
    "青年突击队/志愿队",
    "退役军人事务宣讲",
    "消防安全进校园",
    # 法定与传统节日
    "春节团拜与慰问",
    "元宵灯会与民俗",
    "清明纪念与公益",
    "劳动节表彰与慰问",
    "青年节主题活动",
    "端午节民俗与食品安全",
    "儿童节校园嘉年华",
    "建党节专题学习",
    "建军节双拥活动",
    "教师节感恩主题",
    "中秋节团圆与家书",
    "国庆节主题宣传",
    "重阳节敬老活动",
    "七夕文旅市集",
    "元旦跨年晚会",
    "校庆/院庆纪念",
    "开业周年庆典",
    "丰收节与乡村振兴",
)

_THEME_ANGLES: tuple[str, ...] = (
    "产品发布会",
    "内部汇报",
    "客户提案",
    "培训课件",
    "活动招商手册",
    "年终复盘",
    "品牌故事分享",
    "项目立项说明",
    "校园讲座",
    "行业沙龙开场",
    "述职报告",
    "季度工作汇报",
    "民主生活会发言提纲",
    "党建专题学习课件",
    "主题党日活动方案",
    "团建方案与行程说明",
    "班会课课件",
    "家长会沟通材料",
    "开学第一课",
    "毕业典礼致辞稿提纲",
    "节日活动策划案",
    "节庆开场致辞",
    "表彰大会主持串场",
    "慰问活动介绍",
    "入职培训首日",
    "安全教育专题课",
    "志愿服务招募说明",
    "竞赛动员会",
)

_INSPIRE_DOMAINS: tuple[str, ...] = (
    "本地餐饮连锁",
    "文旅景区运营",
    "K12 或成人教育",
    "社区医疗/康养",
    "业余体育俱乐部",
    "独立音乐/话剧演出",
    "新消费零售",
    "有机农场直供",
    "传统工厂产线班组",
    "环保公益活动",
    "家居生活方式品牌",
    "亲子早教机构",
    "独立游戏发行",
    "非遗手作工坊",
    "律所新人培训",
    "婚礼策划公司",
    "街道党建服务中心",
    "企业党支部主题党日",
    "高三班级冲刺动员",
    "小学中队主题班会",
    "互联网公司部门团建",
    "机关干部年度述职",
    "国庆节社区文艺晚会",
    "中秋节员工家书征集",
    "端午节包粽子公益市集",
    "春节送温暖慰问",
    "教师节师生座谈会",
    "儿童节校园开放日",
    "重阳节敬老院探访",
    "劳动节劳模事迹分享",
    "建党节微党课",
    "元旦跨年晚会策划",
    "校庆七十周年纪念",
    "消防安全进班级宣讲",
    "青年志愿者暑期实践",
)


def generate_random_theme_prompt(*, visual_style: str = "") -> dict[str, str]:
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    domain = random.choice(_THEME_DOMAINS)
    angle = random.choice(_THEME_ANGLES)
    system = (
        "你是 PPT 主题文案助手。只输出一段中文「主题描述」（1–3 句），不要标题、不要列表、不要引号、不要 markdown。\n"
        "要求：\n"
        "- 必须围绕给定「领域」与「场合」发明一个具体、可感知的内容主题（真实业务/活动/议题口吻）\n"
        "- 写具体名词：单位/班级/品牌/活动名、受众、要讲清的一件事；少用空泛形容词\n"
        "- 党建/班级/述职/团建/节日类要贴合对应语境（庄重、校园、复盘或节庆氛围），不要写成科技发布会口吻\n"
        "- 禁止把视觉风格名或设计隐喻写成主题\n"
        "- 严禁套路词堆砌：智慧城市、智能交通、未来出行、数字化转型、赋能、生态闭环、新质生产力、元宇宙\n"
        "- 不要默认写成科技/城市/交通题材，除非领域本身就是这些\n"
        "- 控制在 40–90 个汉字"
    )
    user = (
        f"发散编号：{salt}\n"
        f"领域：{domain}\n"
        f"场合：{angle}\n"
    )
    if visual_style.strip():
        user += f"当前选用视觉风格 id（仅供语气参考，勿写入主题文案）：{visual_style.strip()}\n"
    user += "请按上述领域与场合发明一个具体的 PPT 主题描述。"
    out = _chat(system, user, temperature=1.35)
    return {"prompt": out["text"], "model": out["model"]}


def generate_inspire_brief() -> dict[str, str]:
    """Homepage「发现灵感」：一段可直接当 PPT 创作要求的中文简述（与模板无关）。"""
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    domain = random.choice(_INSPIRE_DOMAINS)
    system = (
        "你是 PPT 需求文案助手。只输出一段中文「PPT 创作要求」（2–4 句），"
        "不要标题、不要列表、不要引号、不要 markdown、不要编号。\n"
        "要求：\n"
        "- 必须围绕给定领域发明一个具体、可做的演示主题\n"
        "- 写清场景或受众、要讲清的核心信息，可带页数或结构偏好\n"
        "- 党建/班级/述职/团建/节日类要贴合语境，语气可庄重、校园或节庆，勿写成空洞科技口号\n"
        "- 语气像用户写给 AI 做网页 PPT 的需求，可直接粘贴使用\n"
        "- 禁止写视觉风格名、配色口号或空洞形容词堆砌\n"
        "- 严禁套路：智慧城市、智能交通、未来出行、数字化转型、赋能、新质生产力\n"
        "- 控制在 60–140 个汉字"
    )
    user = (
        f"发散编号：{salt}\n"
        f"领域：{domain}\n"
        "请写出一段可直接使用的 PPT 创作要求。"
    )
    out = _chat(system, user, temperature=1.3, max_tokens=280)
    return {"prompt": out["text"], "model": out["model"]}


def generate_random_style_intent() -> dict[str, Any]:
    salt = f"{int(time.time() * 1000):x}-{random.randrange(1 << 24):x}"
    # 压低「纸感暖奶油」先验；多数抽冷浅 / 深色 / 高饱和
    field_axes = (
        ("冷白浅底（近纯白或略冷灰白，禁止米色奶油）", 22),
        ("冷灰浅底（蓝灰/绿灰浅场，禁止暖米黄）", 15),
        ("深色哑光底（炭黑/墨绿/藏青，低反光）", 25),
        ("高饱和色块底（大胆单色或双色块，非纸感）", 18),
        ("纯色大胆底（印刷 spot 感，干净平整）", 8),
        ("纸质暖色底（牛皮/米纸/奶油场——仅当 intentionally 纸感）", 12),
    )
    labels = [x[0] for x in field_axes]
    weights = [x[1] for x in field_axes]
    field = random.choices(labels, weights=weights, k=1)[0]
    system = (
        "你是视觉风格策划。只输出一段中文风格意图（1–2 句），描述色调、材质、气质与禁忌。"
        "不要输出风格 id，不要 markdown。\n"
        "必须服从给定「底色轴」；除非底色轴是纸质暖色，禁止写成默认米色/奶油/暖白纸感。"
    )
    user = (
        f"发散编号：{salt}\n"
        f"底色轴：{field}\n"
        "请发明一个适合网页 PPT 的视觉风格意图。"
    )
    out = _chat(system, user, temperature=1.25, max_tokens=180)
    return {
        "mode": "invent",
        "styleIntent": out["text"],
        "model": out["model"],
        "ensureStyle": True,
        "fieldAxis": field,
    }
