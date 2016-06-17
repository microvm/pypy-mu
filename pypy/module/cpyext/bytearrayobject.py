from rpython.rtyper.lltypesystem import rffi, lltype
from rpython.rlib.objectmodel import specialize, we_are_translated
from pypy.interpreter.error import OperationError, oefmt
from pypy.objspace.std.bytearrayobject import new_bytearray
from pypy.module.cpyext.api import (
    cpython_api, cpython_struct, bootstrap_function, build_type_checkers,
    PyVarObjectFields, Py_ssize_t, CONST_STRING, CANNOT_FAIL)
from pypy.module.cpyext.pyerrors import PyErr_BadArgument
from pypy.module.cpyext.pyobject import (
    PyObject, PyObjectP, Py_DecRef, make_ref, from_ref, track_reference,
    make_typedescr, get_typedescr, Py_IncRef)
# Type PyByteArrayObject represents a mutable array of bytes.
# The Python API is that of a sequence;
# the bytes are mapped to ints in [0, 256).
# Bytes are not characters; they may be used to encode characters.
# The only way to go between bytes and str/unicode is via encoding
# and decoding.
# For the convenience of C programmers, the bytes type is considered
# to contain a char pointer, not an unsigned char pointer.

# Expose data as a rw cchar* only through PyByteArray_AsString
# Under this strategy the pointer could loose its synchronization with
# the underlying space.w_bytearray if PyByteArray_Resize is called, so
# hopefully the use of the pointer is short-lived

PyByteArrayObjectStruct = lltype.ForwardReference()
PyByteArrayObject = lltype.Ptr(PyByteArrayObjectStruct)
PyByteArrayObjectFields = PyVarObjectFields 
#    (("ob_exports", rffi.INT), ("ob_alloc", rffi.LONG), ("ob_bytes", rffi.CCHARP))
cpython_struct("PyByteArrayObject", PyByteArrayObjectFields, PyByteArrayObjectStruct)

@bootstrap_function
def init_bytearrayobject(space):
    "Type description of PyByteArrayObject"
    #make_typedescr(space.w_bytearray.layout.typedef,
    #               basestruct=PyByteArrayObject.TO,
    #               attach=bytearray_attach,
    #               dealloc=bytearray_dealloc,
    #               realize=bytearray_realize)

PyByteArray_Check, PyByteArray_CheckExact = build_type_checkers("ByteArray", "w_bytearray")

# XXX dead code to be removed
#def bytearray_attach(space, py_obj, w_obj):
#    """
#    Fills a newly allocated PyByteArrayObject with the given bytearray object
#    """
#    py_ba = rffi.cast(PyByteArrayObject, py_obj)
#    py_ba.c_ob_size = len(space.str_w(w_obj))
#    py_ba.c_ob_bytes = lltype.nullptr(rffi.CCHARP.TO)
#    py_ba.c_ob_exports = rffi.cast(rffi.INT, 0)

#def bytearray_realize(space, py_obj):
#    """
#    Creates the bytearray in the interpreter. 
#    """
#    py_ba = rffi.cast(PyByteArrayObject, py_obj)
#    if not py_ba.c_ob_bytes:
#        py_ba.c_buffer = lltype.malloc(rffi.CCHARP.TO, py_ba.c_ob_size + 1,
#                                    flavor='raw', zero=True)
#    s = rffi.charpsize2str(py_ba.c_ob_bytes, py_ba.c_ob_size)
#    w_obj = space.wrap(s)
#    py_ba.c_ob_exports = rffi.cast(rffi.INT, 0)
#    track_reference(space, py_obj, w_obj)
#    return w_obj

#@cpython_api([PyObject], lltype.Void, header=None)
#def bytearray_dealloc(space, py_obj):
#    """Frees allocated PyByteArrayObject resources.
#    """
#    py_ba = rffi.cast(PyByteArrayObject, py_obj)
#    if py_ba.c_ob_bytes:
#        lltype.free(py_ba.c_ob_bytes, flavor="raw")
#    from pypy.module.cpyext.object import PyObject_dealloc
#    PyObject_dealloc(space, py_obj)

#_______________________________________________________________________

@cpython_api([PyObject], PyObject, result_is_ll=True)
def PyByteArray_FromObject(space, w_obj):
    """Return a new bytearray object from any object, o, that implements the
    buffer protocol.

    XXX expand about the buffer protocol, at least somewhere"""
    w_buffer = space.call_function(space.w_bytearray, w_obj)
    return make_ref(space, w_buffer)

@cpython_api([CONST_STRING, Py_ssize_t], PyObject, result_is_ll=True)
def PyByteArray_FromStringAndSize(space, char_p, length):
    """Create a new bytearray object from string and its length, len.  On
    failure, NULL is returned."""
    if char_p:
        w_s = space.wrap(rffi.charpsize2str(char_p, length))
    else:
        w_s = space.wrap(length)
    w_buffer = space.call_function(space.w_bytearray, w_s)
    return make_ref(space, w_buffer)

@cpython_api([PyObject, PyObject], PyObject)
def PyByteArray_Concat(space, w_left, w_right):
    """Concat bytearrays a and b and return a new bytearray with the result."""
    return space.add(w_left, w_right)

@cpython_api([PyObject], Py_ssize_t, error=-1)
def PyByteArray_Size(space, w_obj):
    """Return the size of bytearray after checking for a NULL pointer."""
    if not w_obj:
        return 0
    return space.len_w(w_obj)

@cpython_api([PyObject], rffi.CCHARP, error=0)
def PyByteArray_AsString(space, w_obj):
    """Return the contents of bytearray as a char array after checking for a
    NULL pointer."""
    if space.isinstance_w(w_obj, space.w_bytearray):
        return w_obj.nonmovable_carray(space)
    else:
        raise oefmt(space.w_TypeError,
                    "expected bytearray object, %T found", w_obj)

@cpython_api([PyObject, Py_ssize_t], rffi.INT_real, error=-1)
def PyByteArray_Resize(space, w_obj, newlen):
    """Resize the internal buffer of bytearray to len."""
    if space.isinstance_w(w_obj, space.w_bytearray):
        oldlen = space.len_w(w_obj)
        if newlen > oldlen:
            space.call_method(w_obj, 'extend', space.wrap('\x00' * (newlen - oldlen)))
        elif oldlen > newlen:
            assert newlen >= 0
            space.delslice(w_obj, space.wrap(newlen), space.wrap(oldlen))
        return 0
    else:
        raise oefmt(space.w_TypeError,
                    "expected bytearray object, %T found", w_obj)
