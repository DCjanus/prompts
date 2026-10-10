"""两平台共用的协作声明决策与正文处理。"""

ENGLISH = (
    "---\n\nI’m happy to make further changes based on feedback. "
    "If it’s easier to edit this PR directly or implement an alternative, "
    "feel free to do so without checking with me first."
)
CHINESE = (
    "---\n\n我很乐意根据反馈继续调整；如果直接修改或另行实现更方便，"
    "维护者也无需事先与我确认。"
)


def decide(mode: str, maintainer: bool | None, assigned: bool) -> tuple[bool, str]:
    """无法确认身份时保留声明，已确认的省略条件优先。"""
    if mode == "always":
        return True, "explicit-always"
    if mode == "never":
        return False, "explicit-never"
    if assigned:
        return False, "actor-is-assignee"
    if maintainer:
        return False, "actor-is-maintainer"
    return True, "identity-unknown" if maintainer is None else "external-contribution"


def render(body: str, include: bool, notice: str) -> str:
    """仅替换正文末尾完整匹配的标准声明，保留其它内容。"""
    result = body.rstrip()
    for known in {ENGLISH, ENGLISH.replace("this PR", "this MR"), CHINESE, notice}:
        if result == known:
            result = ""
            break
        suffix = "\n\n" + known
        if result.endswith(suffix):
            result = result[: -len(suffix)].rstrip()
            break
    if include:
        result = f"{result}\n\n{notice}" if result else notice
    return result + "\n"
