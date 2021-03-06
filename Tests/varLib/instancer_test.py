from fontTools.misc.py23 import *
from fontTools import ttLib
from fontTools import designspaceLib
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib.tables import _f_v_a_r, _g_l_y_f
from fontTools.ttLib.tables import otTables
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools import varLib
from fontTools.varLib import instancer
from fontTools.varLib.mvar import MVAR_ENTRIES
from fontTools.varLib import builder
from fontTools.varLib import featureVars
from fontTools.varLib import models
import collections
from copy import deepcopy
import logging
import os
import re
import pytest


TESTDATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def varfont():
    f = ttLib.TTFont()
    f.importXML(os.path.join(TESTDATA, "PartialInstancerTest-VF.ttx"))
    return f


@pytest.fixture(params=[True, False], ids=["optimize", "no-optimize"])
def optimize(request):
    return request.param


@pytest.fixture
def fvarAxes():
    wght = _f_v_a_r.Axis()
    wght.axisTag = Tag("wght")
    wght.minValue = 100
    wght.defaultValue = 400
    wght.maxValue = 900
    wdth = _f_v_a_r.Axis()
    wdth.axisTag = Tag("wdth")
    wdth.minValue = 70
    wdth.defaultValue = 100
    wdth.maxValue = 100
    return [wght, wdth]


def _get_coordinates(varfont, glyphname):
    # converts GlyphCoordinates to a list of (x, y) tuples, so that pytest's
    # assert will give us a nicer diff
    return list(varfont["glyf"].getCoordinatesAndControls(glyphname, varfont)[0])


class InstantiateGvarTest(object):
    @pytest.mark.parametrize("glyph_name", ["hyphen"])
    @pytest.mark.parametrize(
        "location, expected",
        [
            pytest.param(
                {"wdth": -1.0},
                {
                    "hyphen": [
                        (27, 229),
                        (27, 310),
                        (247, 310),
                        (247, 229),
                        (0, 0),
                        (274, 0),
                        (0, 536),
                        (0, 0),
                    ]
                },
                id="wdth=-1.0",
            ),
            pytest.param(
                {"wdth": -0.5},
                {
                    "hyphen": [
                        (33.5, 229),
                        (33.5, 308.5),
                        (264.5, 308.5),
                        (264.5, 229),
                        (0, 0),
                        (298, 0),
                        (0, 536),
                        (0, 0),
                    ]
                },
                id="wdth=-0.5",
            ),
            # an axis pinned at the default normalized location (0.0) means
            # the default glyf outline stays the same
            pytest.param(
                {"wdth": 0.0},
                {
                    "hyphen": [
                        (40, 229),
                        (40, 307),
                        (282, 307),
                        (282, 229),
                        (0, 0),
                        (322, 0),
                        (0, 536),
                        (0, 0),
                    ]
                },
                id="wdth=0.0",
            ),
        ],
    )
    def test_pin_and_drop_axis(self, varfont, glyph_name, location, expected, optimize):
        instancer.instantiateGvar(varfont, location, optimize=optimize)

        assert _get_coordinates(varfont, glyph_name) == expected[glyph_name]

        # check that the pinned axis has been dropped from gvar
        assert not any(
            "wdth" in t.axes
            for tuples in varfont["gvar"].variations.values()
            for t in tuples
        )

    def test_full_instance(self, varfont, optimize):
        instancer.instantiateGvar(
            varfont, {"wght": 0.0, "wdth": -0.5}, optimize=optimize
        )

        assert _get_coordinates(varfont, "hyphen") == [
            (33.5, 229),
            (33.5, 308.5),
            (264.5, 308.5),
            (264.5, 229),
            (0, 0),
            (298, 0),
            (0, 536),
            (0, 0),
        ]

        assert "gvar" not in varfont

    def test_composite_glyph_not_in_gvar(self, varfont):
        """ The 'minus' glyph is a composite glyph, which references 'hyphen' as a
        component, but has no tuple variations in gvar table, so the component offset
        and the phantom points do not change; however the sidebearings and bounding box
        do change as a result of the parent glyph 'hyphen' changing.
        """
        hmtx = varfont["hmtx"]
        vmtx = varfont["vmtx"]

        hyphenCoords = _get_coordinates(varfont, "hyphen")
        assert hyphenCoords == [
            (40, 229),
            (40, 307),
            (282, 307),
            (282, 229),
            (0, 0),
            (322, 0),
            (0, 536),
            (0, 0),
        ]
        assert hmtx["hyphen"] == (322, 40)
        assert vmtx["hyphen"] == (536, 229)

        minusCoords = _get_coordinates(varfont, "minus")
        assert minusCoords == [(0, 0), (0, 0), (422, 0), (0, 536), (0, 0)]
        assert hmtx["minus"] == (422, 40)
        assert vmtx["minus"] == (536, 229)

        location = {"wght": -1.0, "wdth": -1.0}

        instancer.instantiateGvar(varfont, location)

        # check 'hyphen' coordinates changed
        assert _get_coordinates(varfont, "hyphen") == [
            (26, 259),
            (26, 286),
            (237, 286),
            (237, 259),
            (0, 0),
            (263, 0),
            (0, 536),
            (0, 0),
        ]
        # check 'minus' coordinates (i.e. component offset and phantom points)
        # did _not_ change
        assert _get_coordinates(varfont, "minus") == minusCoords

        assert hmtx["hyphen"] == (263, 26)
        assert vmtx["hyphen"] == (536, 250)

        assert hmtx["minus"] == (422, 26)  # 'minus' left sidebearing changed
        assert vmtx["minus"] == (536, 250)  # 'minus' top sidebearing too


class InstantiateCvarTest(object):
    @pytest.mark.parametrize(
        "location, expected",
        [
            pytest.param({"wght": -1.0}, [500, -400, 150, 250], id="wght=-1.0"),
            pytest.param({"wdth": -1.0}, [500, -400, 180, 200], id="wdth=-1.0"),
            pytest.param({"wght": -0.5}, [500, -400, 165, 250], id="wght=-0.5"),
            pytest.param({"wdth": -0.3}, [500, -400, 180, 235], id="wdth=-0.3"),
        ],
    )
    def test_pin_and_drop_axis(self, varfont, location, expected):
        instancer.instantiateCvar(varfont, location)

        assert list(varfont["cvt "].values) == expected

        # check that the pinned axis has been dropped from cvar
        pinned_axes = location.keys()
        assert not any(
            axis in t.axes for t in varfont["cvar"].variations for axis in pinned_axes
        )

    def test_full_instance(self, varfont):
        instancer.instantiateCvar(varfont, {"wght": -0.5, "wdth": -0.5})

        assert list(varfont["cvt "].values) == [500, -400, 165, 225]

        assert "cvar" not in varfont


class InstantiateMVARTest(object):
    @pytest.mark.parametrize(
        "location, expected",
        [
            pytest.param(
                {"wght": 1.0},
                {"strs": 100, "undo": -200, "unds": 150, "xhgt": 530},
                id="wght=1.0",
            ),
            pytest.param(
                {"wght": 0.5},
                {"strs": 75, "undo": -150, "unds": 100, "xhgt": 515},
                id="wght=0.5",
            ),
            pytest.param(
                {"wght": 0.0},
                {"strs": 50, "undo": -100, "unds": 50, "xhgt": 500},
                id="wght=0.0",
            ),
            pytest.param(
                {"wdth": -1.0},
                {"strs": 20, "undo": -100, "unds": 50, "xhgt": 500},
                id="wdth=-1.0",
            ),
            pytest.param(
                {"wdth": -0.5},
                {"strs": 35, "undo": -100, "unds": 50, "xhgt": 500},
                id="wdth=-0.5",
            ),
            pytest.param(
                {"wdth": 0.0},
                {"strs": 50, "undo": -100, "unds": 50, "xhgt": 500},
                id="wdth=0.0",
            ),
        ],
    )
    def test_pin_and_drop_axis(self, varfont, location, expected):
        mvar = varfont["MVAR"].table
        # initially we have two VarData: the first contains deltas associated with 3
        # regions: 1 with only wght, 1 with only wdth, and 1 with both wght and wdth
        assert len(mvar.VarStore.VarData) == 2
        assert mvar.VarStore.VarRegionList.RegionCount == 3
        assert mvar.VarStore.VarData[0].VarRegionCount == 3
        assert all(len(item) == 3 for item in mvar.VarStore.VarData[0].Item)
        # The second VarData has deltas associated only with 1 region (wght only).
        assert mvar.VarStore.VarData[1].VarRegionCount == 1
        assert all(len(item) == 1 for item in mvar.VarStore.VarData[1].Item)

        instancer.instantiateMVAR(varfont, location)

        for mvar_tag, expected_value in expected.items():
            table_tag, item_name = MVAR_ENTRIES[mvar_tag]
            assert getattr(varfont[table_tag], item_name) == expected_value

        # check that regions and accompanying deltas have been dropped
        num_regions_left = len(mvar.VarStore.VarRegionList.Region)
        assert num_regions_left < 3
        assert mvar.VarStore.VarRegionList.RegionCount == num_regions_left
        assert mvar.VarStore.VarData[0].VarRegionCount == num_regions_left
        # VarData subtables have been merged
        assert len(mvar.VarStore.VarData) == 1

    @pytest.mark.parametrize(
        "location, expected",
        [
            pytest.param(
                {"wght": 1.0, "wdth": 0.0},
                {"strs": 100, "undo": -200, "unds": 150},
                id="wght=1.0,wdth=0.0",
            ),
            pytest.param(
                {"wght": 0.0, "wdth": -1.0},
                {"strs": 20, "undo": -100, "unds": 50},
                id="wght=0.0,wdth=-1.0",
            ),
            pytest.param(
                {"wght": 0.5, "wdth": -0.5},
                {"strs": 55, "undo": -145, "unds": 95},
                id="wght=0.5,wdth=-0.5",
            ),
            pytest.param(
                {"wght": 1.0, "wdth": -1.0},
                {"strs": 50, "undo": -180, "unds": 130},
                id="wght=0.5,wdth=-0.5",
            ),
        ],
    )
    def test_full_instance(self, varfont, location, expected):
        instancer.instantiateMVAR(varfont, location)

        for mvar_tag, expected_value in expected.items():
            table_tag, item_name = MVAR_ENTRIES[mvar_tag]
            assert getattr(varfont[table_tag], item_name) == expected_value

        assert "MVAR" not in varfont


class InstantiateHVARTest(object):
    # the 'expectedDeltas' below refer to the VarData item deltas for the "hyphen"
    # glyph in the PartialInstancerTest-VF.ttx test font, that are left after
    # partial instancing
    @pytest.mark.parametrize(
        "location, expectedRegions, expectedDeltas",
        [
            ({"wght": -1.0}, [{"wdth": (-1.0, -1.0, 0)}], [-59]),
            ({"wght": 0}, [{"wdth": (-1.0, -1.0, 0)}], [-48]),
            ({"wght": 1.0}, [{"wdth": (-1.0, -1.0, 0)}], [7]),
            (
                {"wdth": -1.0},
                [
                    {"wght": (-1.0, -1.0, 0.0)},
                    {"wght": (0.0, 0.6099854, 1.0)},
                    {"wght": (0.6099854, 1.0, 1.0)},
                ],
                [-11, 31, 51],
            ),
            ({"wdth": 0}, [{"wght": (0.6099854, 1.0, 1.0)}], [-4]),
        ],
    )
    def test_partial_instance(self, varfont, location, expectedRegions, expectedDeltas):
        instancer.instantiateHVAR(varfont, location)

        assert "HVAR" in varfont
        hvar = varfont["HVAR"].table
        varStore = hvar.VarStore

        regions = varStore.VarRegionList.Region
        fvarAxes = [a for a in varfont["fvar"].axes if a.axisTag not in location]
        regionDicts = [reg.get_support(fvarAxes) for reg in regions]
        assert len(regionDicts) == len(expectedRegions)
        for region, expectedRegion in zip(regionDicts, expectedRegions):
            assert region.keys() == expectedRegion.keys()
            for axisTag, support in region.items():
                assert support == pytest.approx(expectedRegion[axisTag])

        assert len(varStore.VarData) == 1
        assert varStore.VarData[0].ItemCount == 2

        assert hvar.AdvWidthMap is not None
        advWithMap = hvar.AdvWidthMap.mapping

        assert advWithMap[".notdef"] == advWithMap["space"]
        varIdx = advWithMap[".notdef"]
        # these glyphs have no metrics variations in the test font
        assert varStore.VarData[varIdx >> 16].Item[varIdx & 0xFFFF] == (
            [0] * varStore.VarData[0].VarRegionCount
        )

        varIdx = advWithMap["hyphen"]
        assert varStore.VarData[varIdx >> 16].Item[varIdx & 0xFFFF] == expectedDeltas

    def test_full_instance(self, varfont):
        instancer.instantiateHVAR(varfont, {"wght": 0, "wdth": 0})

        assert "HVAR" not in varfont


class InstantiateItemVariationStoreTest(object):
    def test_VarRegion_get_support(self):
        axisOrder = ["wght", "wdth", "opsz"]
        regionAxes = {"wdth": (-1.0, -1.0, 0.0), "wght": (0.0, 1.0, 1.0)}
        region = builder.buildVarRegion(regionAxes, axisOrder)

        assert len(region.VarRegionAxis) == 3
        assert region.VarRegionAxis[2].PeakCoord == 0

        fvarAxes = [SimpleNamespace(axisTag=axisTag) for axisTag in axisOrder]

        assert region.get_support(fvarAxes) == regionAxes

    @pytest.fixture
    def varStore(self):
        return builder.buildVarStore(
            builder.buildVarRegionList(
                [
                    {"wght": (-1.0, -1.0, 0)},
                    {"wght": (0, 0.5, 1.0)},
                    {"wght": (0.5, 1.0, 1.0)},
                    {"wdth": (-1.0, -1.0, 0)},
                    {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)},
                    {"wght": (0, 0.5, 1.0), "wdth": (-1.0, -1.0, 0)},
                    {"wght": (0.5, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)},
                ],
                ["wght", "wdth"],
            ),
            [
                builder.buildVarData([0, 1, 2], [[100, 100, 100], [100, 100, 100]]),
                builder.buildVarData(
                    [3, 4, 5, 6], [[100, 100, 100, 100], [100, 100, 100, 100]]
                ),
            ],
        )

    @pytest.mark.parametrize(
        "location, expected_deltas, num_regions",
        [
            ({"wght": 0}, [[0, 0], [0, 0]], 1),
            ({"wght": 0.25}, [[50, 50], [0, 0]], 1),
            ({"wdth": 0}, [[0, 0], [0, 0]], 3),
            ({"wdth": -0.75}, [[0, 0], [75, 75]], 3),
            ({"wght": 0, "wdth": 0}, [[0, 0], [0, 0]], 0),
            ({"wght": 0.25, "wdth": 0}, [[50, 50], [0, 0]], 0),
            ({"wght": 0, "wdth": -0.75}, [[0, 0], [75, 75]], 0),
        ],
    )
    def test_instantiate_default_deltas(
        self, varStore, fvarAxes, location, expected_deltas, num_regions
    ):
        defaultDeltas = instancer.instantiateItemVariationStore(
            varStore, fvarAxes, location
        )

        defaultDeltaArray = []
        for varidx, delta in sorted(defaultDeltas.items()):
            major, minor = varidx >> 16, varidx & 0xFFFF
            if major == len(defaultDeltaArray):
                defaultDeltaArray.append([])
            assert len(defaultDeltaArray[major]) == minor
            defaultDeltaArray[major].append(delta)

        assert defaultDeltaArray == expected_deltas
        assert varStore.VarRegionList.RegionCount == num_regions


class TupleVarStoreAdapterTest(object):
    def test_instantiate(self):
        regions = [
            {"wght": (-1.0, -1.0, 0)},
            {"wght": (0.0, 1.0, 1.0)},
            {"wdth": (-1.0, -1.0, 0)},
            {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)},
            {"wght": (0, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)},
        ]
        axisOrder = ["wght", "wdth"]
        tupleVarData = [
            [
                TupleVariation({"wght": (-1.0, -1.0, 0)}, [10, 70]),
                TupleVariation({"wght": (0.0, 1.0, 1.0)}, [30, 90]),
                TupleVariation(
                    {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)}, [-40, -100]
                ),
                TupleVariation(
                    {"wght": (0, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)}, [-60, -120]
                ),
            ],
            [
                TupleVariation({"wdth": (-1.0, -1.0, 0)}, [5, 45]),
                TupleVariation(
                    {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)}, [-15, -55]
                ),
                TupleVariation(
                    {"wght": (0, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)}, [-35, -75]
                ),
            ],
        ]
        adapter = instancer._TupleVarStoreAdapter(
            regions, axisOrder, tupleVarData, itemCounts=[2, 2]
        )

        defaultDeltaArray = adapter.instantiate({"wght": 0.5})

        assert defaultDeltaArray == [[15, 45], [0, 0]]
        assert adapter.regions == [{"wdth": (-1.0, -1.0, 0)}]
        assert adapter.tupleVarData == [
            [TupleVariation({"wdth": (-1.0, -1.0, 0)}, [-30, -60])],
            [TupleVariation({"wdth": (-1.0, -1.0, 0)}, [-12, 8])],
        ]

    def test_dropAxes(self):
        regions = [
            {"wght": (-1.0, -1.0, 0)},
            {"wght": (0.0, 1.0, 1.0)},
            {"wdth": (-1.0, -1.0, 0)},
            {"opsz": (0.0, 1.0, 1.0)},
            {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)},
            {"wght": (0, 0.5, 1.0), "wdth": (-1.0, -1.0, 0)},
            {"wght": (0.5, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)},
        ]
        axisOrder = ["wght", "wdth", "opsz"]
        adapter = instancer._TupleVarStoreAdapter(regions, axisOrder, [], itemCounts=[])

        adapter.dropAxes({"wdth"})

        assert adapter.regions == [
            {"wght": (-1.0, -1.0, 0)},
            {"wght": (0.0, 1.0, 1.0)},
            {"opsz": (0.0, 1.0, 1.0)},
            {"wght": (0.0, 0.5, 1.0)},
            {"wght": (0.5, 1.0, 1.0)},
        ]

        adapter.dropAxes({"wght", "opsz"})

        assert adapter.regions == []

    def test_roundtrip(self, fvarAxes):
        regions = [
            {"wght": (-1.0, -1.0, 0)},
            {"wght": (0, 0.5, 1.0)},
            {"wght": (0.5, 1.0, 1.0)},
            {"wdth": (-1.0, -1.0, 0)},
            {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)},
            {"wght": (0, 0.5, 1.0), "wdth": (-1.0, -1.0, 0)},
            {"wght": (0.5, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)},
        ]
        axisOrder = [axis.axisTag for axis in fvarAxes]

        itemVarStore = builder.buildVarStore(
            builder.buildVarRegionList(regions, axisOrder),
            [
                builder.buildVarData(
                    [0, 1, 2, 4, 5, 6],
                    [[10, -20, 30, -40, 50, -60], [70, -80, 90, -100, 110, -120]],
                ),
                builder.buildVarData(
                    [3, 4, 5, 6], [[5, -15, 25, -35], [45, -55, 65, -75]]
                ),
            ],
        )

        adapter = instancer._TupleVarStoreAdapter.fromItemVarStore(
            itemVarStore, fvarAxes
        )

        assert adapter.tupleVarData == [
            [
                TupleVariation({"wght": (-1.0, -1.0, 0)}, [10, 70]),
                TupleVariation({"wght": (0, 0.5, 1.0)}, [-20, -80]),
                TupleVariation({"wght": (0.5, 1.0, 1.0)}, [30, 90]),
                TupleVariation(
                    {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)}, [-40, -100]
                ),
                TupleVariation(
                    {"wght": (0, 0.5, 1.0), "wdth": (-1.0, -1.0, 0)}, [50, 110]
                ),
                TupleVariation(
                    {"wght": (0.5, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)}, [-60, -120]
                ),
            ],
            [
                TupleVariation({"wdth": (-1.0, -1.0, 0)}, [5, 45]),
                TupleVariation(
                    {"wght": (-1.0, -1.0, 0), "wdth": (-1.0, -1.0, 0)}, [-15, -55]
                ),
                TupleVariation(
                    {"wght": (0, 0.5, 1.0), "wdth": (-1.0, -1.0, 0)}, [25, 65]
                ),
                TupleVariation(
                    {"wght": (0.5, 1.0, 1.0), "wdth": (-1.0, -1.0, 0)}, [-35, -75]
                ),
            ],
        ]
        assert adapter.itemCounts == [data.ItemCount for data in itemVarStore.VarData]
        assert adapter.regions == regions
        assert adapter.axisOrder == axisOrder

        itemVarStore2 = adapter.asItemVarStore()

        assert [
            reg.get_support(fvarAxes) for reg in itemVarStore2.VarRegionList.Region
        ] == regions

        assert itemVarStore2.VarDataCount == 2
        assert itemVarStore2.VarData[0].VarRegionIndex == [0, 1, 2, 4, 5, 6]
        assert itemVarStore2.VarData[0].Item == [
            [10, -20, 30, -40, 50, -60],
            [70, -80, 90, -100, 110, -120],
        ]
        assert itemVarStore2.VarData[1].VarRegionIndex == [3, 4, 5, 6]
        assert itemVarStore2.VarData[1].Item == [[5, -15, 25, -35], [45, -55, 65, -75]]


def makeTTFont(glyphOrder, features):
    font = ttLib.TTFont()
    font.setGlyphOrder(glyphOrder)
    addOpenTypeFeaturesFromString(font, features)
    font["name"] = ttLib.newTable("name")
    return font


def _makeDSAxesDict(axes):
    dsAxes = collections.OrderedDict()
    for axisTag, axisValues in axes:
        axis = designspaceLib.AxisDescriptor()
        axis.name = axis.tag = axis.labelNames["en"] = axisTag
        axis.minimum, axis.default, axis.maximum = axisValues
        dsAxes[axis.tag] = axis
    return dsAxes


def makeVariableFont(masters, baseIndex, axes, masterLocations):
    vf = deepcopy(masters[baseIndex])
    dsAxes = _makeDSAxesDict(axes)
    fvar = varLib._add_fvar(vf, dsAxes, instances=())
    axisTags = [axis.axisTag for axis in fvar.axes]
    normalizedLocs = [models.normalizeLocation(m, dict(axes)) for m in masterLocations]
    model = models.VariationModel(normalizedLocs, axisOrder=axisTags)
    varLib._merge_OTL(vf, model, masters, axisTags)
    return vf


def makeParametrizedVF(glyphOrder, features, values, increments):
    # Create a test VF with given glyphs and parametrized OTL features.
    # The VF is built from 9 masters (3 x 3 along wght and wdth), with
    # locations hard-coded and base master at wght=400 and wdth=100.
    # 'values' is a list of initial values that are interpolated in the
    # 'features' string, and incremented for each subsequent master by the
    # given 'increments' (list of 2-tuple) along the two axes.
    assert values and len(values) == len(increments)
    assert all(len(i) == 2 for i in increments)
    masterLocations = [
        {"wght": 100, "wdth": 50},
        {"wght": 100, "wdth": 100},
        {"wght": 100, "wdth": 150},
        {"wght": 400, "wdth": 50},
        {"wght": 400, "wdth": 100},  # base master
        {"wght": 400, "wdth": 150},
        {"wght": 700, "wdth": 50},
        {"wght": 700, "wdth": 100},
        {"wght": 700, "wdth": 150},
    ]
    n = len(values)
    values = list(values)
    masters = []
    for _ in range(3):
        for _ in range(3):
            master = makeTTFont(glyphOrder, features=features % tuple(values))
            masters.append(master)
            for i in range(n):
                values[i] += increments[i][1]
        for i in range(n):
            values[i] += increments[i][0]
    baseIndex = 4
    axes = [("wght", (100, 400, 700)), ("wdth", (50, 100, 150))]
    vf = makeVariableFont(masters, baseIndex, axes, masterLocations)
    return vf


@pytest.fixture
def varfontGDEF():
    glyphOrder = [".notdef", "f", "i", "f_i"]
    features = (
        "feature liga { sub f i by f_i;} liga;"
        "table GDEF { LigatureCaretByPos f_i %d; } GDEF;"
    )
    values = [100]
    increments = [(+30, +10)]
    return makeParametrizedVF(glyphOrder, features, values, increments)


@pytest.fixture
def varfontGPOS():
    glyphOrder = [".notdef", "V", "A"]
    features = "feature kern { pos V A %d; } kern;"
    values = [-80]
    increments = [(-10, -5)]
    return makeParametrizedVF(glyphOrder, features, values, increments)


@pytest.fixture
def varfontGPOS2():
    glyphOrder = [".notdef", "V", "A", "acutecomb"]
    features = (
        "markClass [acutecomb] <anchor 150 -10> @TOP_MARKS;"
        "feature mark {"
        "  pos base A <anchor %d 450> mark @TOP_MARKS;"
        "} mark;"
        "feature kern {"
        "  pos V A %d;"
        "} kern;"
    )
    values = [200, -80]
    increments = [(+30, +10), (-10, -5)]
    return makeParametrizedVF(glyphOrder, features, values, increments)


class InstantiateOTLTest(object):
    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0}, 110),  # -60
            ({"wght": 0}, 170),
            ({"wght": 0.5}, 200),  # +30
            ({"wght": 1.0}, 230),  # +60
            ({"wdth": -1.0}, 160),  # -10
            ({"wdth": -0.3}, 167),  # -3
            ({"wdth": 0}, 170),
            ({"wdth": 1.0}, 180),  # +10
        ],
    )
    def test_pin_and_drop_axis_GDEF(self, varfontGDEF, location, expected):
        vf = varfontGDEF
        assert "GDEF" in vf

        instancer.instantiateOTL(vf, location)

        assert "GDEF" in vf
        gdef = vf["GDEF"].table
        assert gdef.Version == 0x00010003
        assert gdef.VarStore
        assert gdef.LigCaretList
        caretValue = gdef.LigCaretList.LigGlyph[0].CaretValue[0]
        assert caretValue.Format == 3
        assert hasattr(caretValue, "DeviceTable")
        assert caretValue.DeviceTable.DeltaFormat == 0x8000
        assert caretValue.Coordinate == expected

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0, "wdth": -1.0}, 100),  # -60 - 10
            ({"wght": -1.0, "wdth": 0.0}, 110),  # -60
            ({"wght": -1.0, "wdth": 1.0}, 120),  # -60 + 10
            ({"wght": 0.0, "wdth": -1.0}, 160),  # -10
            ({"wght": 0.0, "wdth": 0.0}, 170),
            ({"wght": 0.0, "wdth": 1.0}, 180),  # +10
            ({"wght": 1.0, "wdth": -1.0}, 220),  # +60 - 10
            ({"wght": 1.0, "wdth": 0.0}, 230),  # +60
            ({"wght": 1.0, "wdth": 1.0}, 240),  # +60 + 10
        ],
    )
    def test_full_instance_GDEF(self, varfontGDEF, location, expected):
        vf = varfontGDEF
        assert "GDEF" in vf

        instancer.instantiateOTL(vf, location)

        assert "GDEF" in vf
        gdef = vf["GDEF"].table
        assert gdef.Version == 0x00010000
        assert not hasattr(gdef, "VarStore")
        assert gdef.LigCaretList
        caretValue = gdef.LigCaretList.LigGlyph[0].CaretValue[0]
        assert caretValue.Format == 1
        assert not hasattr(caretValue, "DeviceTable")
        assert caretValue.Coordinate == expected

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0}, -85),  # +25
            ({"wght": 0}, -110),
            ({"wght": 1.0}, -135),  # -25
            ({"wdth": -1.0}, -105),  # +5
            ({"wdth": 0}, -110),
            ({"wdth": 1.0}, -115),  # -5
        ],
    )
    def test_pin_and_drop_axis_GPOS_kern(self, varfontGPOS, location, expected):
        vf = varfontGPOS
        assert "GDEF" in vf
        assert "GPOS" in vf

        instancer.instantiateOTL(vf, location)

        gdef = vf["GDEF"].table
        gpos = vf["GPOS"].table
        assert gdef.Version == 0x00010003
        assert gdef.VarStore

        assert gpos.LookupList.Lookup[0].LookupType == 2  # PairPos
        pairPos = gpos.LookupList.Lookup[0].SubTable[0]
        valueRec1 = pairPos.PairSet[0].PairValueRecord[0].Value1
        assert valueRec1.XAdvDevice
        assert valueRec1.XAdvDevice.DeltaFormat == 0x8000
        assert valueRec1.XAdvance == expected

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0, "wdth": -1.0}, -80),  # +25 + 5
            ({"wght": -1.0, "wdth": 0.0}, -85),  # +25
            ({"wght": -1.0, "wdth": 1.0}, -90),  # +25 - 5
            ({"wght": 0.0, "wdth": -1.0}, -105),  # +5
            ({"wght": 0.0, "wdth": 0.0}, -110),
            ({"wght": 0.0, "wdth": 1.0}, -115),  # -5
            ({"wght": 1.0, "wdth": -1.0}, -130),  # -25 + 5
            ({"wght": 1.0, "wdth": 0.0}, -135),  # -25
            ({"wght": 1.0, "wdth": 1.0}, -140),  # -25 - 5
        ],
    )
    def test_full_instance_GPOS_kern(self, varfontGPOS, location, expected):
        vf = varfontGPOS
        assert "GDEF" in vf
        assert "GPOS" in vf

        instancer.instantiateOTL(vf, location)

        assert "GDEF" not in vf
        gpos = vf["GPOS"].table

        assert gpos.LookupList.Lookup[0].LookupType == 2  # PairPos
        pairPos = gpos.LookupList.Lookup[0].SubTable[0]
        valueRec1 = pairPos.PairSet[0].PairValueRecord[0].Value1
        assert not hasattr(valueRec1, "XAdvDevice")
        assert valueRec1.XAdvance == expected

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0}, (210, -85)),  # -60, +25
            ({"wght": 0}, (270, -110)),
            ({"wght": 0.5}, (300, -122)),  # +30, -12
            ({"wght": 1.0}, (330, -135)),  # +60, -25
            ({"wdth": -1.0}, (260, -105)),  # -10, +5
            ({"wdth": -0.3}, (267, -108)),  # -3, +2
            ({"wdth": 0}, (270, -110)),
            ({"wdth": 1.0}, (280, -115)),  # +10, -5
        ],
    )
    def test_pin_and_drop_axis_GPOS_mark_and_kern(
        self, varfontGPOS2, location, expected
    ):
        vf = varfontGPOS2
        assert "GDEF" in vf
        assert "GPOS" in vf

        instancer.instantiateOTL(vf, location)

        v1, v2 = expected
        gdef = vf["GDEF"].table
        gpos = vf["GPOS"].table
        assert gdef.Version == 0x00010003
        assert gdef.VarStore
        assert gdef.GlyphClassDef

        assert gpos.LookupList.Lookup[0].LookupType == 4  # MarkBasePos
        markBasePos = gpos.LookupList.Lookup[0].SubTable[0]
        baseAnchor = markBasePos.BaseArray.BaseRecord[0].BaseAnchor[0]
        assert baseAnchor.Format == 3
        assert baseAnchor.XDeviceTable
        assert baseAnchor.XDeviceTable.DeltaFormat == 0x8000
        assert not baseAnchor.YDeviceTable
        assert baseAnchor.XCoordinate == v1
        assert baseAnchor.YCoordinate == 450

        assert gpos.LookupList.Lookup[1].LookupType == 2  # PairPos
        pairPos = gpos.LookupList.Lookup[1].SubTable[0]
        valueRec1 = pairPos.PairSet[0].PairValueRecord[0].Value1
        assert valueRec1.XAdvDevice
        assert valueRec1.XAdvDevice.DeltaFormat == 0x8000
        assert valueRec1.XAdvance == v2

    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": -1.0, "wdth": -1.0}, (200, -80)),  # -60 - 10, +25 + 5
            ({"wght": -1.0, "wdth": 0.0}, (210, -85)),  # -60, +25
            ({"wght": -1.0, "wdth": 1.0}, (220, -90)),  # -60 + 10, +25 - 5
            ({"wght": 0.0, "wdth": -1.0}, (260, -105)),  # -10, +5
            ({"wght": 0.0, "wdth": 0.0}, (270, -110)),
            ({"wght": 0.0, "wdth": 1.0}, (280, -115)),  # +10, -5
            ({"wght": 1.0, "wdth": -1.0}, (320, -130)),  # +60 - 10, -25 + 5
            ({"wght": 1.0, "wdth": 0.0}, (330, -135)),  # +60, -25
            ({"wght": 1.0, "wdth": 1.0}, (340, -140)),  # +60 + 10, -25 - 5
        ],
    )
    def test_full_instance_GPOS_mark_and_kern(self, varfontGPOS2, location, expected):
        vf = varfontGPOS2
        assert "GDEF" in vf
        assert "GPOS" in vf

        instancer.instantiateOTL(vf, location)

        v1, v2 = expected
        gdef = vf["GDEF"].table
        gpos = vf["GPOS"].table
        assert gdef.Version == 0x00010000
        assert not hasattr(gdef, "VarStore")
        assert gdef.GlyphClassDef

        assert gpos.LookupList.Lookup[0].LookupType == 4  # MarkBasePos
        markBasePos = gpos.LookupList.Lookup[0].SubTable[0]
        baseAnchor = markBasePos.BaseArray.BaseRecord[0].BaseAnchor[0]
        assert baseAnchor.Format == 1
        assert not hasattr(baseAnchor, "XDeviceTable")
        assert not hasattr(baseAnchor, "YDeviceTable")
        assert baseAnchor.XCoordinate == v1
        assert baseAnchor.YCoordinate == 450

        assert gpos.LookupList.Lookup[1].LookupType == 2  # PairPos
        pairPos = gpos.LookupList.Lookup[1].SubTable[0]
        valueRec1 = pairPos.PairSet[0].PairValueRecord[0].Value1
        assert not hasattr(valueRec1, "XAdvDevice")
        assert valueRec1.XAdvance == v2


class InstantiateAvarTest(object):
    @pytest.mark.parametrize("location", [{"wght": 0.0}, {"wdth": 0.0}])
    def test_pin_and_drop_axis(self, varfont, location):
        instancer.instantiateAvar(varfont, location)

        assert set(varfont["avar"].segments).isdisjoint(location)

    def test_full_instance(self, varfont):
        instancer.instantiateAvar(varfont, {"wght": 0.0, "wdth": 0.0})

        assert "avar" not in varfont


class InstantiateFvarTest(object):
    @pytest.mark.parametrize(
        "location, instancesLeft",
        [
            (
                {"wght": 400.0},
                ["Regular", "SemiCondensed", "Condensed", "ExtraCondensed"],
            ),
            (
                {"wght": 100.0},
                ["Thin", "SemiCondensed Thin", "Condensed Thin", "ExtraCondensed Thin"],
            ),
            (
                {"wdth": 100.0},
                [
                    "Thin",
                    "ExtraLight",
                    "Light",
                    "Regular",
                    "Medium",
                    "SemiBold",
                    "Bold",
                    "ExtraBold",
                    "Black",
                ],
            ),
            # no named instance at pinned location
            ({"wdth": 90.0}, []),
        ],
    )
    def test_pin_and_drop_axis(self, varfont, location, instancesLeft):
        instancer.instantiateFvar(varfont, location)

        fvar = varfont["fvar"]
        assert {a.axisTag for a in fvar.axes}.isdisjoint(location)

        for instance in fvar.instances:
            assert set(instance.coordinates).isdisjoint(location)

        name = varfont["name"]
        assert [
            name.getDebugName(instance.subfamilyNameID) for instance in fvar.instances
        ] == instancesLeft

    def test_full_instance(self, varfont):
        instancer.instantiateFvar(varfont, {"wght": 0.0, "wdth": 0.0})

        assert "fvar" not in varfont


class InstantiateSTATTest(object):
    @pytest.mark.parametrize(
        "location, expected",
        [
            ({"wght": 400}, ["Condensed", "Upright"]),
            ({"wdth": 100}, ["Thin", "Regular", "Black", "Upright"]),
        ],
    )
    def test_pin_and_drop_axis(self, varfont, location, expected):
        instancer.instantiateSTAT(varfont, location)

        stat = varfont["STAT"].table
        designAxes = {a.AxisTag for a in stat.DesignAxisRecord.Axis}

        assert designAxes == {"wght", "wdth", "ital"}.difference(location)

        name = varfont["name"]
        valueNames = []
        for axisValueTable in stat.AxisValueArray.AxisValue:
            valueName = name.getDebugName(axisValueTable.ValueNameID)
            valueNames.append(valueName)

        assert valueNames == expected

    def test_skip_empty_table(self, varfont):
        stat = otTables.STAT()
        stat.Version = 0x00010001
        stat.populateDefaults()
        assert not stat.DesignAxisRecord
        assert not stat.AxisValueArray
        varfont["STAT"].table = stat

        instancer.instantiateSTAT(varfont, {"wght": 100})

        assert not varfont["STAT"].table.DesignAxisRecord

    def test_drop_table(self, varfont):
        stat = otTables.STAT()
        stat.Version = 0x00010001
        stat.populateDefaults()
        stat.DesignAxisRecord = otTables.AxisRecordArray()
        axis = otTables.AxisRecord()
        axis.AxisTag = "wght"
        axis.AxisNameID = 0
        axis.AxisOrdering = 0
        stat.DesignAxisRecord.Axis = [axis]
        varfont["STAT"].table = stat

        instancer.instantiateSTAT(varfont, {"wght": 100})

        assert "STAT" not in varfont


def test_pruningUnusedNames(varfont):
    varNameIDs = instancer.getVariationNameIDs(varfont)

    assert varNameIDs == set(range(256, 296 + 1))

    fvar = varfont["fvar"]
    stat = varfont["STAT"].table

    with instancer.pruningUnusedNames(varfont):
        del fvar.axes[0]  # Weight (nameID=256)
        del fvar.instances[0]  # Thin (nameID=258)
        del stat.DesignAxisRecord.Axis[0]  # Weight (nameID=256)
        del stat.AxisValueArray.AxisValue[0]  # Thin (nameID=258)

    assert not any(n for n in varfont["name"].names if n.nameID in {256, 258})

    with instancer.pruningUnusedNames(varfont):
        del varfont["fvar"]
        del varfont["STAT"]

    assert not any(n for n in varfont["name"].names if n.nameID in varNameIDs)
    assert "ltag" not in varfont


def test_setMacOverlapFlags():
    flagOverlapCompound = _g_l_y_f.OVERLAP_COMPOUND
    flagOverlapSimple = _g_l_y_f.flagOverlapSimple

    glyf = ttLib.newTable("glyf")
    glyf.glyphOrder = ["a", "b", "c"]
    a = _g_l_y_f.Glyph()
    a.numberOfContours = 1
    a.flags = [0]
    b = _g_l_y_f.Glyph()
    b.numberOfContours = -1
    comp = _g_l_y_f.GlyphComponent()
    comp.flags = 0
    b.components = [comp]
    c = _g_l_y_f.Glyph()
    c.numberOfContours = 0
    glyf.glyphs = {"a": a, "b": b, "c": c}

    instancer.setMacOverlapFlags(glyf)

    assert a.flags[0] & flagOverlapSimple != 0
    assert b.components[0].flags & flagOverlapCompound != 0


def _strip_ttLibVersion(string):
    return re.sub(' ttLibVersion=".*"', "", string)


@pytest.fixture
def varfont2():
    f = ttLib.TTFont(recalcTimestamp=False)
    f.importXML(os.path.join(TESTDATA, "PartialInstancerTest2-VF.ttx"))
    return f


def _dump_ttx(ttFont):
    # compile to temporary bytes stream, reload and dump to XML
    tmp = BytesIO()
    ttFont.save(tmp)
    tmp.seek(0)
    ttFont2 = ttLib.TTFont(tmp, recalcBBoxes=False, recalcTimestamp=False)
    s = StringIO()
    ttFont2.saveXML(s, newlinestr="\n")
    return _strip_ttLibVersion(s.getvalue())


def _get_expected_instance_ttx(wght, wdth):
    with open(
        os.path.join(
            TESTDATA,
            "test_results",
            "PartialInstancerTest2-VF-instance-{0},{1}.ttx".format(wght, wdth),
        ),
        "r",
        encoding="utf-8",
    ) as fp:
        return _strip_ttLibVersion(fp.read())


class InstantiateVariableFontTest(object):
    @pytest.mark.parametrize(
        "wght, wdth",
        [(100, 100), (400, 100), (900, 100), (100, 62.5), (400, 62.5), (900, 62.5)],
    )
    def test_multiple_instancing(self, varfont2, wght, wdth):
        partial = instancer.instantiateVariableFont(varfont2, {"wght": wght})
        instance = instancer.instantiateVariableFont(partial, {"wdth": wdth})

        expected = _get_expected_instance_ttx(wght, wdth)

        assert _dump_ttx(instance) == expected

    def test_default_instance(self, varfont2):
        instance = instancer.instantiateVariableFont(
            varfont2, {"wght": None, "wdth": None}
        )

        expected = _get_expected_instance_ttx(400, 100)

        assert _dump_ttx(instance) == expected


def _conditionSetAsDict(conditionSet, axisOrder):
    result = {}
    for cond in conditionSet.ConditionTable:
        assert cond.Format == 1
        axisTag = axisOrder[cond.AxisIndex]
        result[axisTag] = (cond.FilterRangeMinValue, cond.FilterRangeMaxValue)
    return result


def _getSubstitutions(gsub, lookupIndices):
    subs = {}
    for index, lookup in enumerate(gsub.LookupList.Lookup):
        if index in lookupIndices:
            for subtable in lookup.SubTable:
                subs.update(subtable.mapping)
    return subs


def makeFeatureVarsFont(conditionalSubstitutions):
    axes = set()
    glyphs = set()
    for region, substitutions in conditionalSubstitutions:
        for box in region:
            axes.update(box.keys())
        glyphs.update(*substitutions.items())

    varfont = ttLib.TTFont()
    varfont.setGlyphOrder(sorted(glyphs))

    fvar = varfont["fvar"] = ttLib.newTable("fvar")
    fvar.axes = []
    for axisTag in sorted(axes):
        axis = _f_v_a_r.Axis()
        axis.axisTag = Tag(axisTag)
        fvar.axes.append(axis)

    featureVars.addFeatureVariations(varfont, conditionalSubstitutions)

    return varfont


class InstantiateFeatureVariationsTest(object):
    @pytest.mark.parametrize(
        "location, appliedSubs, expectedRecords",
        [
            ({"wght": 0}, {}, [({"cntr": (0.75, 1.0)}, {"uni0041": "uni0061"})]),
            (
                {"wght": -1.0},
                {},
                [
                    ({"cntr": (0, 0.25)}, {"uni0061": "uni0041"}),
                    ({"cntr": (0.75, 1.0)}, {"uni0041": "uni0061"}),
                ],
            ),
            (
                {"wght": 1.0},
                {"uni0024": "uni0024.nostroke"},
                [
                    (
                        {"cntr": (0.75, 1.0)},
                        {"uni0024": "uni0024.nostroke", "uni0041": "uni0061"},
                    )
                ],
            ),
            (
                {"cntr": 0},
                {},
                [
                    ({"wght": (-1.0, -0.45654)}, {"uni0061": "uni0041"}),
                    ({"wght": (0.20886, 1.0)}, {"uni0024": "uni0024.nostroke"}),
                ],
            ),
            (
                {"cntr": 1.0},
                {"uni0041": "uni0061"},
                [
                    (
                        {"wght": (0.20886, 1.0)},
                        {"uni0024": "uni0024.nostroke", "uni0041": "uni0061"},
                    )
                ],
            ),
        ],
    )
    def test_partial_instance(self, location, appliedSubs, expectedRecords):
        font = makeFeatureVarsFont(
            [
                ([{"wght": (0.20886, 1.0)}], {"uni0024": "uni0024.nostroke"}),
                ([{"cntr": (0.75, 1.0)}], {"uni0041": "uni0061"}),
                (
                    [{"wght": (-1.0, -0.45654), "cntr": (0, 0.25)}],
                    {"uni0061": "uni0041"},
                ),
            ]
        )

        instancer.instantiateFeatureVariations(font, location)

        gsub = font["GSUB"].table
        featureVariations = gsub.FeatureVariations

        assert featureVariations.FeatureVariationCount == len(expectedRecords)

        axisOrder = [a.axisTag for a in font["fvar"].axes if a.axisTag not in location]
        for i, (expectedConditionSet, expectedSubs) in enumerate(expectedRecords):
            rec = featureVariations.FeatureVariationRecord[i]
            conditionSet = _conditionSetAsDict(rec.ConditionSet, axisOrder)

            assert conditionSet == expectedConditionSet

            subsRecord = rec.FeatureTableSubstitution.SubstitutionRecord[0]
            lookupIndices = subsRecord.Feature.LookupListIndex
            substitutions = _getSubstitutions(gsub, lookupIndices)

            assert substitutions == expectedSubs

        appliedLookupIndices = gsub.FeatureList.FeatureRecord[0].Feature.LookupListIndex

        assert _getSubstitutions(gsub, appliedLookupIndices) == appliedSubs

    @pytest.mark.parametrize(
        "location, appliedSubs",
        [
            ({"wght": 0, "cntr": 0}, None),
            ({"wght": -1.0, "cntr": 0}, {"uni0061": "uni0041"}),
            ({"wght": 1.0, "cntr": 0}, {"uni0024": "uni0024.nostroke"}),
            ({"wght": 0.0, "cntr": 1.0}, {"uni0041": "uni0061"}),
            (
                {"wght": 1.0, "cntr": 1.0},
                {"uni0041": "uni0061", "uni0024": "uni0024.nostroke"},
            ),
            ({"wght": -1.0, "cntr": 0.3}, None),
        ],
    )
    def test_full_instance(self, location, appliedSubs):
        font = makeFeatureVarsFont(
            [
                ([{"wght": (0.20886, 1.0)}], {"uni0024": "uni0024.nostroke"}),
                ([{"cntr": (0.75, 1.0)}], {"uni0041": "uni0061"}),
                (
                    [{"wght": (-1.0, -0.45654), "cntr": (0, 0.25)}],
                    {"uni0061": "uni0041"},
                ),
            ]
        )

        instancer.instantiateFeatureVariations(font, location)

        gsub = font["GSUB"].table
        assert not hasattr(gsub, "FeatureVariations")

        if appliedSubs:
            lookupIndices = gsub.FeatureList.FeatureRecord[0].Feature.LookupListIndex
            assert _getSubstitutions(gsub, lookupIndices) == appliedSubs
        else:
            assert not gsub.FeatureList.FeatureRecord

    def test_unsupported_condition_format(self, caplog):
        font = makeFeatureVarsFont(
            [
                (
                    [{"wdth": (-1.0, -0.5), "wght": (0.5, 1.0)}],
                    {"dollar": "dollar.nostroke"},
                )
            ]
        )
        featureVariations = font["GSUB"].table.FeatureVariations
        rec1 = featureVariations.FeatureVariationRecord[0]
        assert len(rec1.ConditionSet.ConditionTable) == 2
        rec1.ConditionSet.ConditionTable[0].Format = 2

        with caplog.at_level(logging.WARNING, logger="fontTools.varLib.instancer"):
            instancer.instantiateFeatureVariations(font, {"wdth": 0})

        assert (
            "Condition table 0 of FeatureVariationRecord 0 "
            "has unsupported format (2); ignored"
        ) in caplog.text

        # check that record with unsupported condition format (but whose other
        # conditions do not reference pinned axes) is kept as is
        featureVariations = font["GSUB"].table.FeatureVariations
        assert featureVariations.FeatureVariationRecord[0] is rec1
        assert len(rec1.ConditionSet.ConditionTable) == 2
        assert rec1.ConditionSet.ConditionTable[0].Format == 2


@pytest.mark.parametrize(
    "limits, expected",
    [
        (["wght=400", "wdth=100"], {"wght": 400, "wdth": 100}),
        (["wght=400:900"], {"wght": (400, 900)}),
        (["slnt=11.4"], {"slnt": 11.4}),
        (["ABCD=drop"], {"ABCD": None}),
    ],
)
def test_parseLimits(limits, expected):
    assert instancer.parseLimits(limits) == expected


@pytest.mark.parametrize(
    "limits", [["abcde=123", "=0", "wght=:", "wght=1:", "wght=abcd", "wght=x:y"]]
)
def test_parseLimits_invalid(limits):
    with pytest.raises(ValueError, match="invalid location format"):
        instancer.parseLimits(limits)


def test_normalizeAxisLimits_tuple(varfont):
    normalized = instancer.normalizeAxisLimits(varfont, {"wght": (100, 400)})
    assert normalized == {"wght": (-1.0, 0)}


def test_normalizeAxisLimits_no_avar(varfont):
    del varfont["avar"]

    normalized = instancer.normalizeAxisLimits(varfont, {"wght": (500, 600)})

    assert normalized["wght"] == pytest.approx((0.2, 0.4), 1e-4)


def test_normalizeAxisLimits_missing_from_fvar(varfont):
    with pytest.raises(ValueError, match="not present in fvar"):
        instancer.normalizeAxisLimits(varfont, {"ZZZZ": 1000})


def test_sanityCheckVariableTables(varfont):
    font = ttLib.TTFont()
    with pytest.raises(ValueError, match="Missing required table fvar"):
        instancer.sanityCheckVariableTables(font)

    del varfont["glyf"]

    with pytest.raises(ValueError, match="Can't have gvar without glyf"):
        instancer.sanityCheckVariableTables(varfont)


def test_main(varfont, tmpdir):
    fontfile = str(tmpdir / "PartialInstancerTest-VF.ttf")
    varfont.save(fontfile)
    args = [fontfile, "wght=400"]

    # exits without errors
    assert instancer.main(args) is None


def test_main_exit_nonexistent_file(capsys):
    with pytest.raises(SystemExit):
        instancer.main([""])
    captured = capsys.readouterr()

    assert "No such file ''" in captured.err


def test_main_exit_invalid_location(varfont, tmpdir, capsys):
    fontfile = str(tmpdir / "PartialInstancerTest-VF.ttf")
    varfont.save(fontfile)

    with pytest.raises(SystemExit):
        instancer.main([fontfile, "wght:100"])
    captured = capsys.readouterr()

    assert "invalid location format" in captured.err


def test_main_exit_multiple_limits(varfont, tmpdir, capsys):
    fontfile = str(tmpdir / "PartialInstancerTest-VF.ttf")
    varfont.save(fontfile)

    with pytest.raises(SystemExit):
        instancer.main([fontfile, "wght=400", "wght=90"])
    captured = capsys.readouterr()

    assert "Specified multiple limits for the same axis" in captured.err
