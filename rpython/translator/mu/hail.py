"""
Generate the Heap Allocation and Initialisation Language (HAIL) script
to initialise the global cells.
"""
from rpython.mutyper.muts import mutype
from rpython.mutyper.muts.muentity import MuGlobalCell, MuName


class _HAILName:
    _name_dic = {}

    def __init__(self, name):
        if name in _HAILName._name_dic:
            n = _HAILName._name_dic[name] + 1
        else:
            n = 0
        _HAILName._name_dic[name] = n
        self.name = "%s_%d" % (name, n)

    def __str__(self):
        return "$%s" % self.name


class HAILGenerator:
    def __init__(self):
        self.gcells = {}
        self._refs = {}

    def add_gcell(self, gcell):
        self._find_refs(gcell._obj)
        obj = gcell._obj._obj0
        if isinstance(obj, mutype._mustruct):
            obj = obj._top_container()
        self.gcells[gcell] = self._refs[obj]     # Get the HAILName that was assigned to the content of gcell.

    def _find_refs(self, obj):
        if isinstance(obj, (mutype._muref, mutype._muiref)):
            refnt = obj._obj0
            if isinstance(refnt, mutype._mustruct):
                refnt = refnt._top_container()

            if refnt not in self._refs:
                self._refs[refnt] = _HAILName(mutype.mu_typeOf(obj).mu_name._name)
            else:
                return
            self._find_refs(refnt)

        elif isinstance(obj, (mutype._mustruct, mutype._muhybrid)):
            for fld in mutype.mu_typeOf(obj)._flds:
                self._find_refs(obj._getattr(fld))

        elif isinstance(obj, (mutype._mumemarray)):
            if isinstance(obj._OF, (mutype.MuContainerType, mutype.MuRef, mutype.MuIRef)):
                for i in range(len(obj.items)):
                    itm = obj[i]
                    self._find_refs(itm)

    def get_types(self):
        s = set()
        for r in self._refs:
            obj_t = mutype.mu_typeOf(r)
            s.add(obj_t)
        return s

    def codegen(self, fp):
        # Allocate everything first
        for r, n in self._refs.items():
            obj_t = mutype.mu_typeOf(r)
            if isinstance(obj_t, mutype.MuHybrid):
                fp.write(".newhybrid %s <%s> %d\n" % (n, obj_t.mu_name, len(r._getattr(obj_t._varfld))))
            else:
                fp.write(".new %s <%s>\n" % (n, obj_t.mu_name))

        for r, n in self._refs.items():
            fp.write(".init %s = %s\n" % (n, self._getinitstr(r)))

        for gcl, n in self.gcells.items():
            fp.write(".init %s = %s\n" % (gcl.mu_name, n))

    def _getinitstr(self, obj):
        if isinstance(obj, (mutype._muprimitive, mutype._munullref)):
            return repr(obj)

        elif isinstance(obj, (mutype._mustruct, mutype._muhybrid)):
            return "{%s}" % ' '.join([self._getinitstr(obj._getattr(fld)) for fld in mutype.mu_typeOf(obj)._names])

        elif isinstance(obj, mutype._mumemarray):
            return "{%s}" % ' '.join([self._getinitstr(itm) for itm in obj])

        elif isinstance(obj, (mutype._muref, mutype._muiref)):
            refrnt = obj._obj0
            if isinstance(refrnt, mutype._mustruct):
                refrnt = refrnt._top_container()
            assert refrnt in self._refs
            name = self._refs[refrnt]
            if isinstance(name, MuName) and 'gcl' in str(name):
                return "*%s" % name
            return str(name)
        elif isinstance(obj, mutype._mufuncref):
            assert hasattr(obj, 'graph')
            try:
                assert obj.graph.mu_name is not None
                return str(obj.graph.mu_name)
            except AssertionError:
                # Assuming the function has never known to be indirectly called
                # make the reference NULL for now.
                # But the problem lies at the chopper stage
                # where the function graph is chopped.
                # Thus at the chopper stage it needs to consider function references
                # in the reachable struct constants as well.
                # TODO: fix the chopper.
                return "NULL"

        else:
            raise TypeError("Unknown value '%s' of type '%s'." % (obj, mutype.mu_typeOf(obj)))
