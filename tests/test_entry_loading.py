from rainclass.browser import Browser
from rainclass.discovery import CourseDiscovery,HOME

def test_saved_course_is_checked_directly_without_home_or_other_courses(tmp_path):
    import json
    from rainclass.discovery import valid_entry
    from rainclass.real_worker import RealWorker
    entry={'course':'测试课','url':'https://www.yuketang.cn/v2/web/studentLog/2'}
    (tmp_path/'last-class-entry.json').write_text(json.dumps(entry),encoding='utf-8')
    assert RealWorker(tmp_path/'rainclass-edge-profile',tmp_path).last_entry==entry
    assert valid_entry({'course':'x','url':'https://example.com/v2/web/studentLog/2'}) is None
    browser=Browser(tmp_path/'rainclass-edge-profile');browser.open('about:blank');requests=[]
    def route(r):
        requests.append(r.request.url)
        html='''<div class="logs-list"><div class="studentCard">正在上课<h2 onclick="window.tries=(window.tries||0)+1;if(window.tries<2)return;window.open('/lesson/fullscreen/v3/123/ppt/8')">课堂</h2></div></div>'''
        r.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
    browser.context.route('https://www.yuketang.cn/**',route)
    try:
        clock=[0];browser.page.goto(entry['url']);d=CourseDiscovery(lambda t:None,resume=entry,clock=lambda:clock[0])
        for _ in range(5):
            clock[0]+=5
            d.tick(browser.context,True);browser.page.wait_for_timeout(50)
            if any('/lesson/' in p.url for p in browser.context.pages):break
        d._enter(browser.context)
        assert d.last_entry==entry
        assert browser.page.evaluate('window.tries')==2
        assert requests.count(entry['url'])==1 and HOME not in requests
        assert all('/studentLog/' not in u or u==entry['url'] for u in requests)
    finally:browser.close()

def test_cached_course_state_recovers_after_transient_login_home_redirect(tmp_path):
    from tests.test_lifecycle import install_routes
    b=Browser(tmp_path/'rainclass-edge-profile');b.open('about:blank')
    entry={'course':'课程0','url':'https://www.yuketang.cn/v2/web/studentLog/0'}
    try:
        install_routes(b.context);b.page.goto(entry['url'])
        d=CourseDiscovery(lambda t:None,resume=entry)
        # A slow authentication redirect can change the route between sampling ticks.
        d.page=b.page;d.phase='resume';d.names=['课程0'];d.resume=None
        b.page.goto(HOME);assert d.tick(b.context,True)=='NOT_VERIFIED'
        assert d.phase=='home'
        b.page.goto(entry['url']);d.tick(b.context,True)
        b.page.wait_for_timeout(50)
        assert any('/lesson/' in p.url for p in b.context.pages)
    finally:b.close()

def test_delayed_records_whitespace_heading_and_delayed_popup(tmp_path):
    browser=Browser(tmp_path/'rainclass-edge-profile');browser.open('about:blank')
    visits=[0]
    def route(r):
        if '/studentLog/' in r.request.url:
            visits[0]+=1
            html='''<div class="classroom-header-base">课程</div><div class="logs-list"></div>
            <script>setTimeout(()=>{document.querySelector('.logs-list').innerHTML=
            `<div class="studentCard">正在上课<h2 onclick="setTimeout(()=>window.open('/lesson/fullscreen/v3/123/ppt/1'),200)">  测试课堂  </h2></div>`},250)</script>'''
        elif '/lesson/' in r.request.url:html='<p>课堂</p>'
        else:
            html='''<div class="index__view"><div class="el-tabs__item is-active">我听的课</div><section id="cards"></section></div>
            <script>setTimeout(()=>{document.querySelector('#cards').innerHTML=
            `<div class="el-card box-card"><h1 onclick="location.href='/v2/web/studentLog/1'">课程</h1></div>`},250)</script>'''
        r.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
    browser.context.route('https://www.yuketang.cn/**',route)
    try:
        browser.page.goto(HOME);notices=[];d=CourseDiscovery(notices.append)
        for _ in range(50):
            state=d.tick(browser.context,True)
            browser.page.wait_for_timeout(100)
            if any('/lesson/' in p.url for p in browser.context.pages):break
        assert any('/lesson/' in p.url for p in browser.context.pages)
        assert visits[0]==2
        d._enter(browser.context)
        assert d.last_course=='课程'
        assert any('已确认' in n for n in notices)
    finally:browser.close()
