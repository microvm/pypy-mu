from pypy.interpreter.error import oefmt
from rpython.rtyper.lltypesystem import rffi, lltype
from pypy.module.cpyext.api import (
    cpython_api, cpython_struct, bootstrap_function, build_type_checkers,
    PyVarObjectFields, Py_ssize_t, CONST_STRING, CANNOT_FAIL)
from pypy.module.cpyext.pyerrors import PyErr_BadArgument
from pypy.module.cpyext.pyobject import (
    PyObject, PyObjectP, Py_DecRef, make_ref, from_ref, track_reference,
    make_typedescr, get_typedescr, as_pyobj, Py_IncRef, get_w_obj_and_decref)

##
## Implementation of PyStringObject
## ================================
##
## The problem
## -----------
##
## PyString_AsString() must return a (non-movable) pointer to the underlying
## buffer, whereas pypy strings are movable.  C code may temporarily store
## this address and use it, as long as it owns a reference to the PyObject.
## There is no "release" function to specify that the pointer is not needed
## any more.
##
## Also, the pointer may be used to fill the initial value of string. This is
## valid only when the string was just allocated, and is not used elsewhere.
##
## Solution
## --------
##
## PyStringObject contains two additional members: the ob_size and a pointer to a
## char buffer; it may be NULL.
##
## - A string allocated by pypy will be converted into a PyStringObject with a
##   NULL buffer.  The first time PyString_AsString() is called, memory is
##   allocated (with flavor='raw') and content is copied.
##
## - A string allocated with PyString_FromStringAndSize(NULL, size) will
##   allocate a PyStringObject structure, and a buffer with the specified
##   size+1, but the reference won't be stored in the global map; there is no
##   corresponding object in pypy.  When from_ref() or Py_INCREF() is called,
##   the pypy string is created, and added to the global map of tracked
##   objects.  The buffer is then supposed to be immutable.
##
## - _PyString_Resize() works only on not-yet-pypy'd strings, and returns a
##   similar object.
##
## - PyString_Size() doesn't need to force the object.
##
## - There could be an (expensive!) check in from_ref() that the buffer still
##   corresponds to the pypy gc-managed string.
##

PyStringObjectStruct = lltype.ForwardReference()
PyStringObject = lltype.Ptr(PyStringObjectStruct)
PyStringObjectFields = PyVarObjectFields + \
    (("ob_shash", rffi.LONG), ("ob_sstate", rffi.INT), ("buffer", rffi.CCHARP))
cpython_struct("PyStringObject", PyStringObjectFields, PyStringObjectStruct)

@bootstrap_function
def init_stringobject(space):
    "Type description of PyStringObject"
    make_typedescr(space.w_str.layout.typedef,
                   basestruct=PyStringObject.TO,
                   attach=string_attach,
                   dealloc=string_dealloc,
                   realize=string_realize)

PyString_Check, PyString_CheckExact = build_type_checkers("String", "w_str")

def new_empty_str(space, length):
    """
    Allocate a PyStringObject and its buffer, but without a corresponding
    interpreter object.  The buffer may be mutated, until string_realize() is
    called.  Refcount of the result is 1.
    """
    typedescr = get_typedescr(space.w_str.layout.typedef)
    py_obj = typedescr.allocate(space, space.w_str)
    py_str = rffi.cast(PyStringObject, py_obj)

    buflen = length + 1
    py_str.c_ob_size = length
    py_str.c_buffer = lltype.malloc(rffi.CCHARP.TO, buflen,
                                    flavor='raw', zero=True,
                                    add_memory_pressure=True)
    py_str.c_ob_sstate = rffi.cast(rffi.INT, 0) # SSTATE_NOT_INTERNED
    return py_str

def string_attach(space, py_obj, w_obj):
    """
    Fills a newly allocated PyStringObject with the given string object. The
    buffer must not be modified.
    """
    py_str = rffi.cast(PyStringObject, py_obj)
    py_str.c_ob_size = len(space.str_w(w_obj))
    py_str.c_buffer = lltype.nullptr(rffi.CCHARP.TO)
    py_str.c_ob_shash = space.hash_w(w_obj)
    py_str.c_ob_sstate = rffi.cast(rffi.INT, 1) # SSTATE_INTERNED_MORTAL

def string_realize(space, py_obj):
    """
    Creates the string in the interpreter. The PyStringObject buffer must not
    be modified after this call.
    """
    py_str = rffi.cast(PyStringObject, py_obj)
    if not py_str.c_buffer:
        py_str.c_buffer = lltype.malloc(rffi.CCHARP.TO, py_str.c_ob_size + 1,
                                    flavor='raw', zero=True)
    s = rffi.charpsize2str(py_str.c_buffer, py_str.c_ob_size)
    w_obj = space.wrap(s)
    py_str.c_ob_shash = space.hash_w(w_obj)
    py_str.c_ob_sstate = rffi.cast(rffi.INT, 1) # SSTATE_INTERNED_MORTAL
    track_reference(space, py_obj, w_obj)
    return w_obj

@cpython_api([PyObject], lltype.Void, header=None)
def string_dealloc(space, py_obj):
    """Frees allocated PyStringObject resources.
    """
    py_str = rffi.cast(PyStringObject, py_obj)
    if py_str.c_buffer:
        lltype.free(py_str.c_buffer, flavor="raw")
    from pypy.module.cpyext.object import PyObject_dealloc
    PyObject_dealloc(space, py_obj)

#_______________________________________________________________________

@cpython_api([CONST_STRING, Py_ssize_t], PyObject, result_is_ll=True)
def PyString_FromStringAndSize(space, char_p, length):
    if char_p:
        s = rffi.charpsize2str(char_p, length)
        return make_ref(space, space.wrap(s))
    else:
        return rffi.cast(PyObject, new_empty_str(space, length))

@cpython_api([CONST_STRING], PyObject)
def PyString_FromString(space, char_p):
    s = rffi.charp2str(char_p)
    return space.wrap(s)

@cpython_api([PyObject], rffi.CCHARP, error=0)
def PyString_AsString(space, ref):
    if from_ref(space, rffi.cast(PyObject, ref.c_ob_type)) is space.w_str:
        pass    # typecheck returned "ok" without forcing 'ref' at all
    elif not PyString_Check(space, ref):   # otherwise, use the alternate way
        from pypy.module.cpyext.unicodeobject import (
            PyUnicode_Check, _PyUnicode_AsDefaultEncodedString)
        if PyUnicode_Check(space, ref):
            ref = _PyUnicode_AsDefaultEncodedString(space, ref, lltype.nullptr(rffi.CCHARP.TO))
        else:
            raise oefmt(space.w_TypeError,
                        "expected string or Unicode object, %T found",
                        from_ref(space, ref))
    ref_str = rffi.cast(PyStringObject, ref)
    if not ref_str.c_buffer:
        # copy string buffer
        w_str = from_ref(space, ref)
        s = space.str_w(w_str)
        ref_str.c_buffer = rffi.str2charp(s)
    return ref_str.c_buffer

@cpython_api([PyObject, rffi.CCHARPP, rffi.CArrayPtr(Py_ssize_t)], rffi.INT_real, error=-1)
def PyString_AsStringAndSize(space, ref, buffer, length):
    if not PyString_Check(space, ref):
        from pypy.module.cpyext.unicodeobject import (
            PyUnicode_Check, _PyUnicode_AsDefaultEncodedString)
        if PyUnicode_Check(space, ref):
            ref = _PyUnicode_AsDefaultEncodedString(space, ref, lltype.nullptr(rffi.CCHARP.TO))
        else:
            raise oefmt(space.w_TypeError,
                        "expected string or Unicode object, %T found",
                        from_ref(space, ref))
    ref_str = rffi.cast(PyStringObject, ref)
    if not ref_str.c_buffer:
        # copy string buffer
        w_str = from_ref(space, ref)
        s = space.str_w(w_str)
        ref_str.c_buffer = rffi.str2charp(s)
    buffer[0] = ref_str.c_buffer
    if length:
        length[0] = ref_str.c_ob_size
    else:
        i = 0
        while ref_str.c_buffer[i] != '\0':
            i += 1
        if i != ref_str.c_ob_size:
            raise oefmt(space.w_TypeError,
                        "expected string without null bytes")
    return 0

@cpython_api([PyObject], Py_ssize_t, error=-1)
def PyString_Size(space, ref):
    if from_ref(space, rffi.cast(PyObject, ref.c_ob_type)) is space.w_str:
        ref = rffi.cast(PyStringObject, ref)
        return ref.c_ob_size
    else:
        w_obj = from_ref(space, ref)
        return space.len_w(w_obj)

@cpython_api([PyObjectP, Py_ssize_t], rffi.INT_real, error=-1)
def _PyString_Resize(space, ref, newsize):
    """A way to resize a string object even though it is "immutable". Only use this to
    build up a brand new string object; don't use this if the string may already be
    known in other parts of the code.  It is an error to call this function if the
    refcount on the input string object is not one. Pass the address of an existing
    string object as an lvalue (it may be written into), and the new size desired.
    On success, *string holds the resized string object and 0 is returned;
    the address in *string may differ from its input value.  If the reallocation
    fails, the original string object at *string is deallocated, *string is
    set to NULL, a memory exception is set, and -1 is returned.
    """
    # XXX always create a new string so far
    py_str = rffi.cast(PyStringObject, ref[0])
    if not py_str.c_buffer:
        raise oefmt(space.w_SystemError,
                    "_PyString_Resize called on already created string")
    try:
        py_newstr = new_empty_str(space, newsize)
    except MemoryError:
        Py_DecRef(space, ref[0])
        ref[0] = lltype.nullptr(PyObject.TO)
        raise
    to_cp = newsize
    oldsize = py_str.c_ob_size
    if oldsize < newsize:
        to_cp = oldsize
    for i in range(to_cp):
        py_newstr.c_buffer[i] = py_str.c_buffer[i]
    Py_DecRef(space, ref[0])
    ref[0] = rffi.cast(PyObject, py_newstr)
    return 0

@cpython_api([PyObject, PyObject], rffi.INT, error=CANNOT_FAIL)
def _PyString_Eq(space, w_str1, w_str2):
    return space.eq_w(w_str1, w_str2)

@cpython_api([PyObjectP, PyObject], lltype.Void, error=None)
def PyString_Concat(space, ref, w_newpart):
    """Create a new string object in *string containing the contents of newpart
    appended to string; the caller will own the new reference.  The reference to
    the old value of string will be stolen.  If the new string cannot be created,
    the old reference to string will still be discarded and the value of
    *string will be set to NULL; the appropriate exception will be set."""

    old = ref[0]
    if not old:
        return

    ref[0] = lltype.nullptr(PyObject.TO)
    w_str = get_w_obj_and_decref(space, old)
    if w_newpart is not None and PyString_Check(space, old):
        # xxx if w_newpart is not a string or unicode or bytearray,
        # this might call __radd__() on it, whereas CPython raises
        # a TypeError in this case.
        w_newstr = space.add(w_str, w_newpart)
        ref[0] = make_ref(space, w_newstr)

@cpython_api([PyObjectP, PyObject], lltype.Void, error=None)
def PyString_ConcatAndDel(space, ref, newpart):
    """Create a new string object in *string containing the contents of newpart
    appended to string.  This version decrements the reference count of newpart."""
    try:
        PyString_Concat(space, ref, newpart)
    finally:
        Py_DecRef(space, newpart)

@cpython_api([PyObject, PyObject], PyObject)
def PyString_Format(space, w_format, w_args):
    """Return a new string object from format and args. Analogous to format %
    args.  The args argument must be a tuple."""
    return space.mod(w_format, w_args)

@cpython_api([CONST_STRING], PyObject)
def PyString_InternFromString(space, string):
    """A combination of PyString_FromString() and
    PyString_InternInPlace(), returning either a new string object that has
    been interned, or a new ("owned") reference to an earlier interned string
    object with the same value."""
    s = rffi.charp2str(string)
    return space.new_interned_str(s)

@cpython_api([PyObjectP], lltype.Void)
def PyString_InternInPlace(space, string):
    """Intern the argument *string in place.  The argument must be the
    address of a pointer variable pointing to a Python string object.
    If there is an existing interned string that is the same as
    *string, it sets *string to it (decrementing the reference count
    of the old string object and incrementing the reference count of
    the interned string object), otherwise it leaves *string alone and
    interns it (incrementing its reference count).  (Clarification:
    even though there is a lot of talk about reference counts, think
    of this function as reference-count-neutral; you own the object
    after the call if and only if you owned it before the call.)

    This function is not available in 3.x and does not have a PyBytes
    alias."""
    w_str = from_ref(space, string[0])
    w_str = space.new_interned_w_str(w_str)
    Py_DecRef(space, string[0])
    string[0] = make_ref(space, w_str)

@cpython_api([PyObject, CONST_STRING, CONST_STRING], PyObject)
def PyString_AsEncodedObject(space, w_str, encoding, errors):
    """Encode a string object using the codec registered for encoding and return
    the result as Python object. encoding and errors have the same meaning as
    the parameters of the same name in the string encode() method. The codec to
    be used is looked up using the Python codec registry. Return NULL if an
    exception was raised by the codec.

    This function is not available in 3.x and does not have a PyBytes alias."""
    if not PyString_Check(space, w_str):
        PyErr_BadArgument(space)

    w_encoding = w_errors = None
    if encoding:
        w_encoding = space.wrap(rffi.charp2str(encoding))
    if errors:
        w_errors = space.wrap(rffi.charp2str(errors))
    return space.call_method(w_str, 'encode', w_encoding, w_errors)

@cpython_api([PyObject, CONST_STRING, CONST_STRING], PyObject)
def PyString_AsDecodedObject(space, w_str, encoding, errors):
    """Decode a string object by passing it to the codec registered
    for encoding and return the result as Python object. encoding and
    errors have the same meaning as the parameters of the same name in
    the string encode() method.  The codec to be used is looked up
    using the Python codec registry. Return NULL if an exception was
    raised by the codec.

    This function is not available in 3.x and does not have a PyBytes alias."""
    if not PyString_Check(space, w_str):
        PyErr_BadArgument(space)

    w_encoding = w_errors = None
    if encoding:
        w_encoding = space.wrap(rffi.charp2str(encoding))
    if errors:
        w_errors = space.wrap(rffi.charp2str(errors))
    return space.call_method(w_str, "decode", w_encoding, w_errors)

@cpython_api([PyObject, PyObject], PyObject)
def _PyString_Join(space, w_sep, w_seq):
    return space.call_method(w_sep, 'join', w_seq)
