from rainclass.presentation import result_text
from rainclass.ai import RULES,PROMPT_VERSION

def test_chinese_answer_and_cache():
 r=dict(type='single',options=['3','4','5'],stem='2+2=?',suggested_answer=['B'],explanation='相加为4。',uncertainty='仅供参考',source_model='deepseek-flash',cache_status='HIT',duration_ms=2390,token_usage={})
 text=result_text(r)
 assert 'B（4）' in text and '复用历史缓存' in text and '未知' in text
 assert '原分析耗时：2.39 秒' in text
 assert 'Simplified Chinese' in RULES and PROMPT_VERSION.endswith('-zh')

def test_blank_demo():
 text=result_text(dict(type='blank',suggested_answer=['4','6'],status='DEMO'))
 assert '第1空：4；第2空：6' in text and '非真实解答' in text
