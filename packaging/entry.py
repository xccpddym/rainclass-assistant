import sys
if __name__ == '__main__':
    diagnostic=None
    if '--smoke-test' in sys.argv and '--smoke-report' in sys.argv:
        from pathlib import Path
        import faulthandler
        report=Path(sys.argv[sys.argv.index('--smoke-report')+1]).resolve()
        report.parent.mkdir(parents=True,exist_ok=True)
        diagnostic=report.with_suffix('.startup.txt').open('w',encoding='utf-8')
        diagnostic.write('Python entry reached\n');diagnostic.flush()
        faulthandler.dump_traceback_later(30,repeat=True,file=diagnostic)
    from rainclass.app import main
    if diagnostic:diagnostic.write('App import completed\n');diagnostic.flush()
    code=main()
    if diagnostic:faulthandler.cancel_dump_traceback_later();diagnostic.close()
    raise SystemExit(code)
