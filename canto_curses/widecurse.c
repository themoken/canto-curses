/*Canto-curses - ncurses RSS reader
   Copyright (C) 2010 Jack Miller <jack@codezen.org>

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as 
   published by the Free Software Foundation.
*/

#include <Python.h>
#include <py_curses.h>

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

static PyMethodDef MvWMethods[] = {
    {"waddch", py_waddch, METH_VARARGS, "waddch() wrapper."},
    {"wcwidth", py_wcwidth, METH_VARARGS, "wcwidth() wrapper."},
    {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC
initwidecurse(void)
{
    Py_InitModule("widecurse", MvWMethods);
}
