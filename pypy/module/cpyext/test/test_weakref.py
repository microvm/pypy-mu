from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.test.test_api import BaseApiTest

class TestWeakReference(BaseApiTest):
    def test_weakref(self, space, api):
        w_obj = space.w_Exception
        w_ref = api.PyWeakref_NewRef(w_obj, space.w_None)
        assert w_ref is not None
        assert space.is_w(api.PyWeakref_GetObject(w_ref), w_obj)
        assert space.is_w(api.PyWeakref_LockObject(w_ref), w_obj)

        w_obj = space.newtuple([])
        assert api.PyWeakref_NewRef(w_obj, space.w_None) is None
        assert api.PyErr_Occurred() is space.w_TypeError
        api.PyErr_Clear()

    def test_proxy(self, space, api):
        w_obj = space.w_Warning # some weakrefable object
        w_proxy = api.PyWeakref_NewProxy(w_obj, None)
        assert space.unwrap(space.str(w_proxy)) == "<type 'exceptions.Warning'>"
        assert space.unwrap(space.repr(w_proxy)).startswith('<weak')

    def test_weakref_lockobject(self, space, api):
        # some new weakrefable object
        w_obj = space.call_function(space.w_type, space.wrap("newtype"),
                                    space.newtuple([]), space.newdict())
        assert w_obj is not None

        w_ref = api.PyWeakref_NewRef(w_obj, space.w_None)
        assert w_obj is not None

        assert space.is_w(api.PyWeakref_LockObject(w_ref), w_obj)
        del w_obj
        import gc; gc.collect()
        assert space.is_w(api.PyWeakref_LockObject(w_ref), space.w_None)


class AppTestWeakReference(AppTestCpythonExtensionBase):

    def test_weakref_macro(self):
        module = self.import_extension('foo', [
            ("test_macro_cast", "METH_NOARGS",
             """
             // PyExc_Warning is some weak-reffable PyObject*.
             char* dumb_pointer;
             PyObject* weakref_obj = PyWeakref_NewRef(PyExc_Warning, NULL);
             if (!weakref_obj) return weakref_obj;
             // No public PyWeakReference type.
             dumb_pointer = (char*) weakref_obj;

             PyWeakref_GET_OBJECT(weakref_obj);
             PyWeakref_GET_OBJECT(dumb_pointer);

             return weakref_obj;
             """
            )
        ])
        module.test_macro_cast()
