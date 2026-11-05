import os
import pytest
from rainclass.focus_guard import FocusState,restore_background_focus,browser_pid,background_action
from rainclass.browser import Browser


class Native:
    def __init__(self,after,valid=True):self.after=after;self.exists=valid;self.restored=[]
    def snapshot(self):return self.after
    def valid(self,handle):return self.exists
    def restore(self,handle):self.restored.append(handle);return True


@pytest.mark.parametrize('before,after,valid,status,restored',[
    (FocusState(1,10,100),FocusState(2,20,100),True,'RESTORED',[1]),
    (FocusState(1,10,100),FocusState(2,20,101),True,'USER_INPUT',[]),
    (FocusState(1,10,100),FocusState(3,30,100),True,'USER_SWITCHED',[]),
    (FocusState(2,20,100),FocusState(2,20,100),True,'BROWSER_ALREADY_FOREGROUND',[]),
    (FocusState(1,10,100),FocusState(1,10,100),True,'UNCHANGED',[]),
    (FocusState(1,10,100),FocusState(2,20,100),False,'WINDOW_CLOSED',[]),
])
def test_restore_only_automatic_owned_browser_activation(before,after,valid,status,restored):
    native=Native(after,valid)
    assert restore_background_focus(native,before,20)==status and native.restored==restored


def test_classroom_focus_requests_blocked_across_reload_without_affecting_input(tmp_path):
    b=Browser(tmp_path/'rainclass-edge-profile',headless=True)
    try:
        b.open('about:blank')
        b.context.route('https://www.yuketang.cn/**',lambda r:r.fulfill(status=200,content_type='text/html; charset=utf-8',body='<input id="editor"><script>window.focus()</script>'))
        p=b.page;p.goto('https://www.yuketang.cn/lesson/fullscreen/v3/123/ppt/1')
        assert browser_pid(p)>0
        detail={}
        with background_action(p,detail):p.reload(wait_until='domcontentloaded')
        assert p.evaluate('window.focus.name')=='rainclassNoWindowFocus'
        assert p.evaluate('window.focus=()=>{window.focusWasReplaced=true};window.focus();window.focusWasReplaced||false') is False
        if os.name=='nt':assert detail.get('focus_guard')!='UNAVAILABLE'
        p.locator('#editor').focus(timeout=1000)
        assert p.evaluate("document.activeElement.id")=='editor'
        p.goto('https://www.yuketang.cn/v2/web/index')
        assert p.evaluate("Object.getOwnPropertyDescriptor(window,'focus').writable") is True
    finally:b.close()
