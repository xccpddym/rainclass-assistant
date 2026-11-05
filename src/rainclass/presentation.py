"""Plain-text Chinese presentation; never render model output as HTML."""
TYPES={'single':'单选题','multiple':'多选题','blank':'填空题','essay':'简答题'}
STATES={'STOPPED':'已停止','STOPPING':'正在停止','PAUSED':'已暂停','RECOVERING':'断开恢复中','IDLE_NO_CLASS':'暂无课程','IGNORE_PPT':'监测中（普通课件）','UNCERTAIN':'题目待确认','INCOMPLETE':'等待题目加载完整','VERIFIED_QUESTION':'已识别新题','NEEDS_MANUAL':'需人工处理','DUPLICATE':'已识别，等待新题'}
def question_text(q):
 lines=['【发现'+TYPES.get(q.kind,'未知题型')+'】'+q.stem]
 if q.kind in ('single','multiple'):lines += [f'{chr(65+i)}. {x}' for i,x in enumerate(q.options)]
 elif q.kind=='blank':lines.append(f'共 {q.blank_count} 个空')
 lines.append('正在准备分析……')
 return '\n'.join(lines)

def result_text(r,q=None):
 kind=r.get('type');options=q.options if q else r.get('options',[])
 stem=q.stem if q else r.get('stem','')
 answers=r.get('suggested_answer',[]);parts=[]
 for i,a in enumerate(answers):
  if kind=='blank':parts.append(f'第{i+1}空：{a}')
  elif len(a)==1 and 0<=ord(a)-65<len(options):parts.append(f'{a}（{options[ord(a)-65]}）')
  else:parts.append(a)
 demo=r.get('status')=='DEMO'
 usage=r.get('token_usage',{})
 def count(k):return str(usage[k]) if k in usage else '未知'
 lines=['分析结果：'+('【本地演示，非真实解答】' if demo else '【AI参考答案】')]
 if stem:lines.append('题目：'+stem)
 lines+=['建议答案：'+'；'.join(parts),'解析：'+r.get('explanation','未知'),'注意事项：'+r.get('uncertainty','未知'), '来源：'+('本地演示模型' if demo else r.get('source_model','未知'))]
 lines.append('获取方式：'+('复用历史缓存（本次未重新调用模型）' if r.get('cache_status')=='HIT' else '本次生成'))
 lines.append(f"原分析耗时：{r.get('duration_ms',0)/1000:.2f} 秒" if r.get('cache_status')=='HIT' else f"分析耗时：{r.get('duration_ms',0)/1000:.2f} 秒")
 if not demo:
  lines.append('原请求用量：输入 '+count('prompt_tokens')+'，输出 '+count('completion_tokens')+' Token；服务商前缀缓存命中 '+count('prompt_cache_hit_tokens')+'，未命中 '+count('prompt_cache_miss_tokens'))
 return '\n'.join(lines)+'\n'+'─'*32

def usage_text(rows):
 if not rows:return '暂无云端请求记录。'
 def value(x):return '未知' if x is None else str(x)
 return '\n'.join(f"模型：{r['model']}；状态：{'成功' if r['status']=='OK' else '失败'}；请求：{r['requests']}次；输入：{value(r['input_tokens'])}；输出：{value(r['output_tokens'])}；缓存命中：{value(r['cache_hit_tokens'])}；缓存未命中：{value(r['cache_miss_tokens'])}；估算费用：{value(r['estimated_cost'])}" for r in rows)
