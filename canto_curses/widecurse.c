/*Canto-curses - ncurses RSS reader
   Copyright (C) 2010 Jack Miller <jack@codezen.org>

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as 
   published by the Free Software Foundation.
*/

#include <Python.h>
#include <py_curses.h>
#include <readline/readline.h>

static PyObject * py_wcwidth(PyObject *self, PyObject *args)
{
    const char *m_enc;
    wchar_t dest[2];
    char *message;
    int ret, bytes;

    if(!PyArg_ParseTuple(args, "et", &m_enc, &message))
	return NULL;

    bytes = mbtowc(dest, &message[0], 3);
    if(bytes <= 0)
	ret = 0;
    else
        ret = wcwidth(dest[0]);

    PyMem_Free(message);
    return Py_BuildValue("i", ret);
}

static PyObject * py_waddch(PyObject *self, PyObject *args)
{
    char *message, *ret_s;
    const char *m_enc;
    PyObject *window, *ret_o;
    WINDOW *win;
    int x, y;

    /* We use the 'et' format because we don't want Python
       to touch the encoding and generate Unicode Exceptions */

    if(!PyArg_ParseTuple(args, "Oet", &window, &m_enc, &message))
	return NULL;

    if (window != Py_None)
        win = ((PyCursesWindowObject *)window)->win;
    else {
	PyMem_Free(message);
        Py_RETURN_NONE;
    }

    getyx(win, y, x);

    if((unsigned char) message[0] > 0x7F) {
	wchar_t dest[2];
	int bytes;

	bytes = mbtowc(dest, &message[0], 3);

	if (bytes > 0) {
	    waddwstr(win, dest);
	    ret_s = &message[bytes];
	    wmove(win, y, x + wcwidth(dest[0]));
	} else
	    ret_s = &message[1];

    } else {
	waddch(win, message[0]);
	ret_s = &message[1];
	wmove(win, y, x + 1);
    }

    ret_o = Py_BuildValue("s", ret_s);
    PyMem_Free(message);

    return ret_o;
}

static PyObject * py_wsize(PyObject *self, PyObject *args)
{
    return Py_BuildValue("i", sizeof(WINDOW));
}

static WINDOW *rl_input_win = NULL;

int widecurse_rlgetc(FILE *fp)
{
    int ret = wgetch(rl_input_win);

    if (ret == KEY_BACKSPACE)
	ret = (int) '\b';
    return ret;
}

static void *old_rlgetc = NULL;

static PyObject *py_set_input_win(PyObject *self, PyObject *args)
{
    PyObject *window;

    if(!PyArg_ParseTuple(args, "O", &window))
	return NULL;

    if (window != Py_None) {
        rl_input_win = ((PyCursesWindowObject *)window)->win;
        old_rlgetc = rl_getc_function;
	rl_getc_function = widecurse_rlgetc;
    }
    else if(old_rlgetc) {
	rl_getc_function = old_rlgetc;
        old_rlgetc = NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

PyObject *display_callback = NULL;

void widecurse_display_callback(void)
{
    PyObject *arglist;

    arglist = Py_BuildValue("(s)", rl_line_buffer);
    PyObject_CallObject(display_callback, arglist);
    Py_DECREF(arglist);
}

static PyObject *py_set_redisplay_callback(PyObject *self, PyObject *args)
{
    PyObject *callback;

    if(!PyArg_ParseTuple(args, "O", &callback))
	return NULL;

    if(!PyCallable_Check(callback)) {
	PyErr_SetString(PyExc_TypeError, "callback must be callable");
	return NULL;
    }

    Py_XINCREF(callback);
    Py_XDECREF(display_callback);

    display_callback = callback;
    rl_redisplay_function = widecurse_display_callback;

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject *py_readline(PyObject *self, PyObject *args)
{
    PyObject *ret;
    char *line = NULL;

    while (!line)
        line = readline(":");

    ret = Py_BuildValue("s", line);
    return ret;
}

static PyMethodDef WCMethods[] = {
    {"waddch", (PyCFunction)py_waddch, METH_VARARGS, "waddch() wrapper."},
    {"wcwidth", (PyCFunction)py_wcwidth, METH_VARARGS, "wcwidth() wrapper."},
    {"wsize", (PyCFunction)py_wsize, METH_VARARGS, "Returns sizeof(WINDOW)"},
    {"set_input_win", (PyCFunction)py_set_input_win, METH_VARARGS, "Sets input window for readline"},
    {"set_redisplay_callback", (PyCFunction)py_set_redisplay_callback, METH_VARARGS, "Sets redisplay callback"},
    {"readline", (PyCFunction)py_readline, METH_VARARGS, "Call readline"},
    {NULL, NULL},
};

static struct PyModuleDef moduledef = {
	PyModuleDef_HEAD_INIT,
	"widecurse",
	NULL,
	-1,
	WCMethods,
	NULL,
	NULL,
	NULL,
	NULL
};

PyMODINIT_FUNC
PyInit_widecurse(void)
{
    return PyModule_Create(&moduledef);
}
