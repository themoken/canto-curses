/*Canto-curses - ncurses RSS reader
   Copyright (C) 2010 Jack Miller <jack@codezen.org>

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as 
   published by the Free Software Foundation.
*/

#include <Python.h>
#include <py_curses.h>
#include <readline/readline.h>

static PyObject *py_wcwidth(PyObject * self, PyObject * args)
{
	const char *m_enc;
	wchar_t dest[2];
	char *message;
	int ret, bytes;

	if (!PyArg_ParseTuple(args, "et", &m_enc, &message))
		return NULL;

	bytes = mbtowc(dest, &message[0], strlen(message));
	if (bytes < 0)
		ret = bytes;
	else
		ret = wcwidth(dest[0]);

	PyMem_Free(message);
	return Py_BuildValue("i", ret);
}

static PyObject *py_waddch(PyObject * self, PyObject * args)
{
	char *message, *ret_s;
	const char *m_enc;
	PyObject *window, *ret_o;
	WINDOW *win;
	int x, y;

	/* We use the 'et' format because we don't want Python
	   to touch the encoding and generate Unicode Exceptions */

	if (!PyArg_ParseTuple(args, "Oet", &window, &m_enc, &message))
		return NULL;

	if (window != Py_None)
		win = ((PyCursesWindowObject *) window)->win;
	else {
		PyMem_Free(message);
		Py_RETURN_NONE;
	}

	getyx(win, y, x);

	if ((unsigned char)message[0] > 0x7F) {
		wchar_t dest[2];
		int bytes;

		bytes = mbtowc(dest, &message[0], strlen(message));

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

static PyObject *py_wsize(PyObject * self, PyObject * args)
{
	return Py_BuildValue("i", sizeof(WINDOW));
}

/* set_hook and on_hook are taken directly from Python's readline.c and are
 * included to make turning the following code into a patch to it trivial
 */

static PyObject *set_hook(const char *funcname, PyObject ** hook_var,
			  PyObject * args)
{
	PyObject *function = Py_None;
	char buf[80];
	PyOS_snprintf(buf, sizeof(buf), "|O:set_%.50s", funcname);
	if (!PyArg_ParseTuple(args, buf, &function))
		return NULL;
	if (function == Py_None) {
		Py_CLEAR(*hook_var);
	} else if (PyCallable_Check(function)) {
		PyObject *tmp = *hook_var;
		Py_INCREF(function);
		*hook_var = function;
		Py_XDECREF(tmp);
	} else {
		PyErr_Format(PyExc_TypeError,
			     "set_%.50s(func): argument not callable",
			     funcname);
		return NULL;
	}
	Py_RETURN_NONE;
}

static int on_hook(PyObject * func)
{
	int result = 0;
	if (func != NULL) {
		PyObject *r;
		r = PyObject_CallFunction(func, NULL);
		if (r == NULL)
			goto error;
		if (r == Py_None)
			result = 0;
		else {
			result = PyLong_AsLong(r);
			if (result == -1 && PyErr_Occurred())
				goto error;
		}
		Py_DECREF(r);
		goto done;
 error:
		PyErr_Clear();
		Py_XDECREF(r);
 done:
		return result;
	}
	return result;
}

PyObject *display_callback = NULL;

static void widecurse_display_callback(void)
{
	PyGILState_STATE gilstate = PyGILState_Ensure();
	on_hook(display_callback);
	PyGILState_Release(gilstate);
}

PyObject *pygetc = NULL;

static int widecurse_getc(FILE * fp)
{
	int r = 0;

	PyGILState_STATE gilstate = PyGILState_Ensure();
	r = on_hook(pygetc);
	PyGILState_Release(gilstate);
	return r;
}

static PyObject *py_set_redisplay_callback(PyObject * self, PyObject * args)
{
	PyObject *r = set_hook("redisplay_callback", &display_callback, args);
	rl_redisplay_function = widecurse_display_callback;
	return r;
}

static PyObject *py_set_getc(PyObject * self, PyObject * args)
{
	PyObject *r = set_hook("pygetc", &pygetc, args);
	rl_getc_function = widecurse_getc;
	return r;
}

static PyObject *py_raw_readline(PyObject * self, PyObject * args)
{
	FILE *old_out = rl_outstream;
	char *s = NULL;
	int len = 0;

	rl_outstream = fopen("/dev/null", "w");

	s = readline(NULL);
	rl_line_buffer[0] = 0;

	fclose(rl_outstream);
	rl_outstream = old_out;

	if (s == NULL) {
		PyErr_CheckSignals();
		if (!PyErr_Occurred())
			PyErr_SetNone(PyExc_KeyboardInterrupt);
		Py_RETURN_NONE;
	}

	len = strlen(s);
	if (len == 0) {
		Py_RETURN_NONE;
	} else {
		if (len > PY_SSIZE_T_MAX) {
			PyErr_SetString(PyExc_OverflowError,
					"input: input too long");
			Py_RETURN_NONE;
		} else
			return PyUnicode_Decode(s, len, "UTF-8", "ignore");
	}
}

static PyObject *py_get_rlpoint(PyObject * self, PyObject * args)
{
	return Py_BuildValue("i", rl_point);
}

static PyMethodDef WCMethods[] = {
	{"waddch", (PyCFunction) py_waddch, METH_VARARGS, "waddch() wrapper."},
	{"wcwidth", (PyCFunction) py_wcwidth, METH_VARARGS,
	 "wcwidth() wrapper."},
	{"wsize", (PyCFunction) py_wsize, METH_VARARGS,
	 "Returns sizeof(WINDOW)"},
	{"set_redisplay_callback", (PyCFunction) py_set_redisplay_callback,
	 METH_VARARGS, "Sets redisplay callback"},
	{"set_getc", (PyCFunction) py_set_getc, METH_VARARGS,
	 "Set readline to use func for getting characters"},
	{"raw_readline", (PyCFunction) py_raw_readline, METH_VARARGS,
	 "Raw readline()"},
	{"get_rlpoint", (PyCFunction) py_get_rlpoint, METH_VARARGS, "Return current readline cursor position"},
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

PyMODINIT_FUNC PyInit_widecurse(void)
{
	return PyModule_Create(&moduledef);
}
