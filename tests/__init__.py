def do_nothing(*args, **kwargs):
    pass


class FunctionCalled(object):
    def __init__(self, func):
        self.called = False
        self.func = func

    def __call__(self, *args, **kwargs):
        self.called = True
        return self.func(*args, **kwargs)
