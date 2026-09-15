# -*- coding: utf-8 -*-
"""沙箱安全：subprocess 模式语义层检查（正则黑名单的互补纵深防御）。

仅验证纯函数 _sandbox_ast_check / check_denied，不真实执行代码，
避免依赖 numpy/matplotlib 与 subprocess 带来的测试副作用。
"""

from app.agents import tools as _t


def test_ast_blocks_socket_import():
    assert _t._sandbox_ast_check("import socket\nsocket.socket()") is not None


def test_ast_blocks_urllib_import():
    assert _t._sandbox_ast_check("import urllib.request\nurllib.request.urlopen('x')") is not None


def test_ast_blocks_importlib_dynamic():
    # importlib.import_module 不含 socket 字样，正则层漏，AST 拦
    assert _t._sandbox_ast_check("import importlib\nimportlib.import_module('socket')") is not None


def test_ast_blocks_concat_bypass():
    # __import__('soc'+'ket')：拼接绕过，正则层漏，AST 拦
    assert _t._sandbox_ast_check("__import__('soc'+'ket')") is not None


def test_ast_blocks_eval_exec():
    assert _t._sandbox_ast_check("eval('1+1')") is not None
    assert _t._sandbox_ast_check("exec('import os')") is not None


def test_ast_blocks_getattr_builtins():
    # getattr(__builtins__, '__import__')('os') 拼接绕过
    assert _t._sandbox_ast_check("getattr(__builtins__, '__import__')('os')") is not None


def test_ast_blocks_os_remove():
    assert _t._sandbox_ast_check("import os\nos.remove('/tmp/x')") is not None
    assert _t._sandbox_ast_check("import shutil\nshutil.rmtree('/tmp/x')") is not None


def test_ast_allows_data_analysis():
    code = (
        "import numpy as np\n"
        "import matplotlib\n"
        "x = [1, 2, 3]\n"
        "print(sum(x))\n"
        "import statistics\n"
        "print(statistics.mean(x))\n"
    )
    assert _t._sandbox_ast_check(code) is None


def test_deny_regex_blocks_socket_text():
    assert _t.check_denied("x = 'socket'") == "socket"


def test_deny_regex_passes_safe():
    assert _t.check_denied("import numpy as np\nnp.mean([1,2,3])") is None
