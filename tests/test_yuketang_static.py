import pytest
from rainclass.browser import Browser,YuketangAdapter

@pytest.fixture(scope='module')
def edge(tmp_path_factory):
 b=Browser(tmp_path_factory.mktemp('static')/'rainclass-edge-profile')
 page=b.open('about:blank')
 yield page
 b.close()

class StudentPage:
 url='https://www.yuketang.cn/v2/web/index'
 def __init__(self,page,url=None):
  self.page=page
  if url:self.url=url
 def evaluate(self,script):return self.page.evaluate(script)

def test_student_list_with_observed_structure(edge):
 edge.set_content('<div class="index__view"><div class="el-tabs__item is-active">我听的课</div><div class="el-card box-card"><div class="el-card__body"><h1>演示课程</h1><span class="className">演示班级</span></div></div></div>')
 s=YuketangAdapter().snapshot(StudentPage(edge))
 assert s['page_state']=='STUDENT_COURSE_LIST'
 assert s['courses']==[{'name':'演示课程','class_name':'演示班级'}]
 assert s['question'] is None and s['course_active'] is None

@pytest.mark.parametrize('historical',[True,False])
def test_course_detail_is_not_live_question(edge,historical):
 history='<div class="logs-list"><section class="studentCard"><section class="activity__wrap"><h2>A/B/C/D 提交 倒计时 历史题</h2></section></section></div>' if historical else ''
 edge.set_content('<div class="classroom-header-base"><h1 class="title-line"><div class="classroom-ellipsis"><div class="title-inner-wrapper">演示课程</div></div><div class="classroom-ellipsis classroom-title-tag"><div class="title-inner-wrapper">演示班级</div></div></h1></div><span class="rain-tabs__nav-item-text">学习日志</span>'+history)
 s=YuketangAdapter().snapshot(StudentPage(edge,'https://www.yuketang.cn/v2/web/studentLog/demo'))
 assert s['page_state']=='STUDENT_COURSE_DETAIL'
 assert s['selected_course']['name']=='演示课程'
 assert s['historical_log_count']==int(historical)
 assert s['question'] is None and s['detection_status']=='NOT_VERIFIED'

def test_unknown_and_teacher_views(edge):
 edge.set_content('<p>问题 A B C D 提交</p>')
 assert YuketangAdapter().snapshot(StudentPage(edge))['page_state']=='NOT_VERIFIED'
 edge.set_content('<div class="index__view"><div class="el-tabs__item is-active">我教的课</div></div>')
 s=YuketangAdapter().snapshot(StudentPage(edge))
 assert s['page_state']=='TEACHER_VIEW' and not s['courses']

def test_real_adapter_is_read_only():
 assert not hasattr(YuketangAdapter(),'submit')
 class Invalid:url='https://www.yuketang.cn.example.com/'
 with pytest.raises(ValueError):YuketangAdapter().snapshot(Invalid())
