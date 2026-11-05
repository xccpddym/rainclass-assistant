"""Keep automated classroom actions from taking another application's focus."""
import os
from contextlib import contextmanager
from dataclasses import dataclass
from weakref import WeakKeyDictionary,WeakSet

FOCUS_SCRIPT=r'''() => {
 if(location.origin!=='https://www.yuketang.cn'||!/^\/lesson\/fullscreen\/v3\/\d+(?:\/|$)/.test(location.pathname))return;
 // Block only page-script window activation. Element focus and manual Windows
 // activation remain available. Login and course discovery pages are untouched.
 try {
   const blocked=function rainclassNoWindowFocus(){};
   Object.defineProperty(window,'focus',{get:()=>blocked,set:()=>{},configurable:true});
 }catch(e){}
}'''
_pids=WeakKeyDictionary();_installed=WeakSet()

@dataclass(frozen=True)
class FocusState:
    handle:int
    pid:int
    last_input:int

class WindowsFocus:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes;self.types=wintypes;self.api=ctypes.windll.user32
        self.api.GetForegroundWindow.restype=wintypes.HWND
        self.api.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.api.IsWindow.argtypes=[wintypes.HWND]
        self.api.SetForegroundWindow.argtypes=[wintypes.HWND]
        self.api.SetForegroundWindow.restype=wintypes.BOOL
        class LastInput(ctypes.Structure):_fields_=[('cbSize',wintypes.UINT),('dwTime',wintypes.DWORD)]
        self.LastInput=LastInput
    def snapshot(self):
        handle=self.api.GetForegroundWindow();pid=self.types.DWORD();info=self.LastInput()
        info.cbSize=self.ctypes.sizeof(info)
        if not handle or not self.api.GetLastInputInfo(self.ctypes.byref(info)):return None
        self.api.GetWindowThreadProcessId(handle,self.ctypes.byref(pid))
        return FocusState(int(handle),pid.value,info.dwTime)
    def valid(self,handle):return bool(self.api.IsWindow(handle))
    def restore(self,handle):return bool(self.api.SetForegroundWindow(handle))

def restore_background_focus(native,before,browser_pid):
    if before is None or browser_pid is None:return 'UNAVAILABLE'
    if before.pid==browser_pid:return 'BROWSER_ALREADY_FOREGROUND'
    after=native.snapshot()
    if after is None:return 'UNAVAILABLE'
    if after.handle==before.handle:return 'UNCHANGED'
    if after.pid!=browser_pid:return 'USER_SWITCHED'
    if after.last_input!=before.last_input:return 'USER_INPUT'
    if not native.valid(before.handle):return 'WINDOW_CLOSED'
    return 'RESTORED' if native.restore(before.handle) else 'RESTORE_FAILED'

def browser_pid(page):
    context=page.context
    if context in _pids:return _pids[context]
    browser=context.browser
    if browser is None:return None
    session=browser.new_browser_cdp_session()
    try:
        rows=session.send('SystemInfo.getProcessInfo')['processInfo']
        pid=next((int(r['id']) for r in rows if r['type']=='browser'),None)
        if pid is not None:_pids[context]=pid
        return pid
    finally:session.detach()

@contextmanager
def background_action(page,diagnostics):
    native=None;before=None;pid=None
    try:
        if os.name=='nt':
            native=WindowsFocus();before=native.snapshot();pid=browser_pid(page)
    except Exception:pass
    try:
        if page not in _installed:
            page.add_init_script('('+FOCUS_SCRIPT+')()');_installed.add(page)
        page.evaluate(FOCUS_SCRIPT)
    except Exception:pass
    try:yield
    finally:
        if native is not None:
            try:diagnostics['focus_guard']=restore_background_focus(native,before,pid)
            except Exception:diagnostics['focus_guard']='UNAVAILABLE'
