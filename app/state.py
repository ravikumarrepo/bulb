import threading
lock=threading.RLock()
stop_event=threading.Event()
worker=None
items=[]
running=False
message="Ready"
config={}
