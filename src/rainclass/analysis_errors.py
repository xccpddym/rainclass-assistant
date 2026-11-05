"""Allowlisted error descriptions; never display arbitrary provider bodies."""
import re
from .ai import AnalysisError


def public_error(error):
    if not isinstance(error,AnalysisError):return '内部处理异常，请人工核对'
    message=str(error)
    if message in ('Course budget reached','单课预算已达到'):
        return '单课金额预算已达到（失败/未知请求也会保守预留）；请查看真实历史与用量'
    if message in ('Course budget/call limit reached','单课预算或调用上限已达到'):
        return '单课预算或请求次数上限已达到（失败/未知请求也会保守预留）；请查看真实历史与用量'
    if message=='Network/timeout/invalid response; outcome unknown; not retried':
        return '模型网络、超时或响应解析失败，结果未知'
    if message=='API key environment variable is unset':return '模型 Key 环境变量未设置'
    if message=='Blank count mismatch':return 'AI 返回的填空答案数量与核对空数不符'
    if message=='Essay requires one bounded answer':return 'AI 主观题答案格式或长度不合要求（单个答案、最多1000字）'
    if re.fullmatch(r'Provider (?:HTTP error|rejected request): \d{3}',message):return '模型接口返回 HTTP '+message[-3:]
    allowed={
        'AI 无法可靠核对原图，请人工核对','AI 核对选项格式无效',
        'AI 核对题目结构无效，请人工核对','原图选项数与页面控件不一致，请人工核对',
        '页面未确认为主观题，不能自动转入主观题作答','AI 题型与页面不一致',
        '原图无效或过大，请人工核对','自动模式已取消','OCR 文本过长',
        '题目或模式已变化，未继续解题',
    }
    if message in allowed:return message
    return '模型返回格式或内容校验失败，请人工核对'
