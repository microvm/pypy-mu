from ..muentity import MuName, SCOPE_GLOBAL, MuEntity, MuGlobalCell
from rpython.rtyper.test.test_llinterp import gengraph
from rpython.flowspace.model import FunctionGraph
from ...ll2mu import ll2mu_ty, ll2mu_val
from rpython.rtyper.lltypesystem.rstr import STR, malloc
from ..mutype import int64_t


def test_muname():
    n1 = MuName("gbl")
    assert n1.scope == SCOPE_GLOBAL

    # Test duplication
    n2 = MuName("gbl")
    assert n2 == n1     # same name -> same name instance

    def f(x):
        return x + 1

    # A realistic test
    _, _, g = gengraph(f, [int])
    assert isinstance(g, FunctionGraph)
    g.mu_name = MuName(g.name)

    for idx, blk in enumerate(list(g.iterblocks())):
        blk.mu_name = MuName("blk%d" % idx, g)
        for v in blk.getvariables():
            v.mu_name = MuName(v.name, blk)

    v = g.startblock.getvariables()[0]
    assert repr(v.mu_name) == '@f.blk0.x_0'


def test_muentity():
    e = MuEntity(MuName("gbl_entity"))
    assert e.mu_name == MuName("gbl_entity")
    assert e.__name__ == "@gbl_entity"


def test_muglobalcell():
    string = "hello"
    ll_ps = malloc(STR, len(string))
    ll_ps.hash = hash(string)
    for i in range(len(string)):
        ll_ps.chars[i] = string[i]

    mut = ll2mu_ty(ll_ps._TYPE)
    muv = ll2mu_val(ll_ps)
    ir = muv._getiref()
    ir.length._obj = int64_t(len(string))

    gcell = MuGlobalCell(mut)
    assert repr(gcell.mu_name) == "@gclrefhybrpy_string_0_0"
    gcell._obj = muv
    assert gcell._obj == muv
