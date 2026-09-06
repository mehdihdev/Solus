"""Canned Onshape REST payloads for the connector tests (SOLUS-CAD-01).

Shapes follow Onshape's documented REST surface (translation request → poll →
external-data download, plus `parts` metadata for part numbers). Every payload
is trimmed to the fields the connector actually reads.

**Provenance / fidelity note:** these were written from Onshape's public API
documentation, not captured from a live tenant — the connector's HTTP paths and
payload shapes need one live confirmation run before CAD-01 is called done. Each
constant names the endpoint it stands for so that pass is mechanical.
"""

from pathlib import Path

#: GET /api/v6/documents/d/{did}/w/{wid}/currentmicroversion
CURRENT_MICROVERSION = {"microversion": "abc123def456"}
CURRENT_MICROVERSION_NEXT = {"microversion": "999999999999"}

#: GET /api/users/sessioninfo
SESSION_INFO = {
    "id": "5f8a1b2c3d4e5f6a7b8c9d0e",
    "name": "Ada Lovelace",
    "email": "ada@example.com",
}

#: POST /api/v6/assemblies/d/{did}/w/{wid}/e/{eid}/translations
TRANSLATION_STARTED = {
    "id": "translation-req-1",
    "requestState": "ACTIVE",
}

#: GET /api/v8/translations/{requestId}
TRANSLATION_DONE = {
    "id": "translation-req-1",
    "requestState": "DONE",
    "resultExternalDataIds": ["external-data-1"],
}
TRANSLATION_ACTIVE = {"id": "translation-req-1", "requestState": "ACTIVE"}
TRANSLATION_FAILED = {
    "id": "translation-req-1",
    "requestState": "FAILED",
    "failureReason": "element is not an assembly",
}

#: GET /api/v6/parts/d/{did}/w/{wid}/e/{eid}
#: `partNumber` is the W0-08 §5.5 fingerprint channel; Onshape leaves it empty
#: unless the team fills the part-metadata field, which is the honest common case.
PARTS_METADATA = [
    {
        "partId": "JHD",
        "name": "BasePlate",
        "partNumber": "AL-6061-PLATE",
        "material": {"displayName": "Aluminium 6061"},
    },
    {
        "partId": "JID",
        "name": "Peg",
        "partNumber": "DIN-912-M4",
        "material": {"displayName": "Steel"},
    },
    {"partId": "JKD", "name": "Unnumbered", "partNumber": ""},
]

#: The bytes GET /api/v6/documents/d/{did}/externaldata/{fid} returns — the same
#: real AP214 assembly the STEP-parser suite uses, so the connector test exercises
#: the true parse path rather than a stub.
STEP_EXPORT = (Path(__file__).parent / "bracket.step").read_text(encoding="utf-8")


# ---------------------------------------------------------------- SOLUS-ONS-A1
# Read/query payloads for the operations layer. Shapes follow Onshape's public
# OpenAPI spec (https://cad.onshape.com/api/openapi) — each constant names the
# endpoint it stands for so the owed live-confirmation run is mechanical.

#: GET /api/v6/documents/{did}
WORKSPACE_INFO = {"id": "d1", "name": "Rover chassis", "defaultWorkspace": {"id": "w1"}}

#: GET /api/v6/documents?limit=20
DOCUMENT_LIST = {
    "items": [
        {"id": "dA", "name": "Rover chassis", "owner": {"name": "Ada Lovelace"}},
        {"id": "dB", "name": "Gripper", "owner": {"name": "Ada Lovelace"}},
    ],
    "next": None,
}

#: GET /api/v6/documents/d/{did}/w/{wid}/elements
ELEMENT_LIST = [
    {"id": "e1", "name": "Assembly 1", "elementType": "ASSEMBLY"},
    {"id": "e2", "name": "Part Studio 1", "elementType": "PARTSTUDIO"},
]

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/features
#: Onshape wraps every feature in a {btType, message} envelope; the operation
#: flattens `message` so a model never has to know that.
FEATURE_TREE = {
    "features": [
        {
            "btType": "BTMSketch-151",
            "message": {"name": "Sketch 1", "featureId": "F1", "featureType": "newSketch"},
        },
        {
            "btType": "BTMFeature-134",
            "message": {"name": "Extrude 1", "featureId": "F2", "featureType": "extrude"},
        },
    ],
    "serializationVersion": "1.2.7",
    "sourceMicroversion": "mv-abc",
    "libraryVersion": 2522,
}

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/featurespecs
FEATURE_SPECS = {
    "featureSpecs": [
        {
            "message": {
                "featureType": "extrude",
                "featureTypeName": "Extrude",
                "parameterIdToSpec": {"depth": {}, "endBound": {}, "entities": {}},
            }
        },
        {"message": {"featureType": "fillet", "featureTypeName": "Fillet"}},
    ]
}

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/bodydetails?includeGeometricData=true
#: The face/edge ids here ARE the deterministic ids a feature parameter takes.
BODY_DETAILS = {
    "bodies": [
        {
            "id": "B1",
            "type": "solid",
            "faces": [
                {"id": "JCC", "surface": {"type": "plane"}, "area": 0.006},
                {"id": "JCD", "surface": {"type": "cylinder"}, "area": 0.001},
            ],
            "edges": [{"id": "JHO", "geometry": {"type": "line", "length": 0.03}}],
        }
    ],
    "microversionId": "mv-abc",
}

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/massproperties
MASS_PROPERTIES = {
    "bodies": {"-all-": {"mass": [0.42, 0.42, 0.42], "volume": [0.00016, 0.00016, 0.00016]}},
    "microversionId": "mv-abc",
}

#: GET /api/v6/assemblies/d/{did}/w/{wid}/e/{eid}?includeMateFeatures=true
ASSEMBLY_DEFINITION = {
    "rootAssembly": {
        "instances": [
            {"id": "i1", "name": "BasePlate <1>", "type": "Part", "partId": "JHD"},
            {"id": "i2", "name": "Peg <1>", "type": "Part", "partId": "JID"},
        ],
        "features": [{"message": {"featureType": "mate", "name": "Fastened 1", "featureId": "M1"}}],
        "occurrences": [{"path": ["i1"], "transform": [1, 0, 0, 0] * 4}],
    },
    "subAssemblies": [],
}

#: GET /api/v6/variables/d/{did}/w/{wid}/e/{eid}/variables
VARIABLES = [
    {
        "variables": [
            {"name": "width", "type": "LENGTH", "expression": "120 mm", "value": "0.12 m"},
            {"name": "count", "type": "NUMBER", "expression": "4", "value": "4"},
        ]
    }
]


# ---------------------------------------------------------------- SOLUS-ONS-A3
# Write payloads. Provenance, stated precisely because it differs per constant:
#
# * `BTVariableParams` IS fully published in Onshape's OpenAPI spec (required
#   `name`+`type`, `name` matching `^[a-zA-Z_][a-zA-Z0-9_]*$`, optional
#   `expression`/`description`), so VARIABLES-shaped payloads are spec-derived.
# * `BTMParameterQuantity-147` and every other BTM parameter subtype are
#   `btType`-ONLY STUBS in that spec — their value fields are not published
#   anywhere machine-readable. So `onshape.add_feature` never hardcodes a field
#   name: it clones the value field carried by the LIVE `featurespecs` default
#   and replaces only its value. The key names below therefore stand in for
#   "whatever the live default carries", and
#   `test_add_feature_follows_whatever_value_field_the_spec_default_uses` proves
#   the operation does not depend on this fixture having guessed right.
# * The envelope (`BTFeatureDefinitionCall-1406` = feature + serializationVersion
#   + sourceMicroversion + libraryVersion + rejectMicroversionSkew) IS published.

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/featurespecs — with the
#: `defaultValue` objects `onshape.add_feature` uses as parameter templates.
FEATURE_SPECS_WITH_DEFAULTS = {
    "featureSpecs": [
        {
            "message": {
                "featureType": "extrude",
                "featureTypeName": "Extrude",
                "parameterIdToSpec": {
                    "depth": {
                        "btType": "BTParameterSpecQuantity-173",
                        "parameterId": "depth",
                        "defaultValue": {
                            "btType": "BTMParameterQuantity-147",
                            "parameterId": "depth",
                            "expression": "25 mm",
                        },
                    },
                    "entities": {
                        "btType": "BTParameterSpecQuery-174",
                        "parameterId": "entities",
                        "defaultValue": {
                            "btType": "BTMParameterQueryList-148",
                            "parameterId": "entities",
                            "queries": [],
                        },
                    },
                    # No derivable default: the operation must refuse rather than
                    # invent a payload for it.
                    "opaque": {
                        "btType": "BTParameterSpecDatabase-1071",
                        "parameterId": "opaque",
                    },
                },
            }
        }
    ]
}

#: The same spec with a DIFFERENT value field name, proving the operation reads
#: the live default rather than a hardcoded key.
FEATURE_SPECS_ALT_VALUE_FIELD = {
    "featureSpecs": [
        {
            "message": {
                "featureType": "extrude",
                "featureTypeName": "Extrude",
                "parameterIdToSpec": {
                    "depth": {
                        "btType": "BTParameterSpecQuantity-173",
                        "parameterId": "depth",
                        "defaultValue": {
                            "btType": "BTMParameterQuantity-147",
                            "parameterId": "depth",
                            "someOtherValueField": "25 mm",
                        },
                    }
                },
            }
        }
    ]
}

#: POST /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/features
ADD_FEATURE_RESPONSE = {
    "feature": {
        "btType": "BTMFeature-134",
        "featureId": "F9",
        "name": "Boss",
        "featureType": "extrude",
    },
    "featureState": {"featureStatus": "OK"},
    "microversionSkew": False,
}


# ---------------------------------------------------------------- SOLUS-ONS-A4
# Reference resolution + surgical edits. Provenance:
#
# * `bodydetails` face/edge ids ARE the deterministic ids feature parameters
#   take — officially stated ("use this as the deterministicId"). The response's
#   detailed field list is NOT published in the OpenAPI spec (`BTBodyEntity-26`
#   is a `btType`-only stub), so the matcher reads fields tolerantly: a face
#   missing `area` simply loses a size comparison rather than raising.
# * `BTMParameterQueryList-148`'s inner query shape is likewise unpublished, so
#   `onshape.update_feature` CLONES the query object the feature already carries
#   and swaps only its id list.  `FEATURE_TREE_WITH_PARAMETERS` therefore models
#   a feature that HAS such an example (F2) and one that does not (F3), and the
#   second must be refused rather than guessed at.

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/bodydetails?includeGeometricData=true
#: Three planar faces so "the plane" is genuinely ambiguous and has to be
#: narrowed — the case a naive resolver gets wrong by picking the first.
BODY_DETAILS_RICH = {
    "bodies": [
        {
            "id": "B1",
            "type": "solid",
            "faces": [
                {
                    "id": "JBIG",
                    "surface": {"type": "plane", "origin": [0.0, 0.0, 0.05]},
                    "area": 0.0060,
                },
                {
                    "id": "JBIH",
                    "surface": {"type": "plane", "origin": [0.0, 0.0, 0.0]},
                    "area": 0.0030,
                },
                {
                    "id": "JBII",
                    "surface": {"type": "plane", "origin": [0.02, 0.0, 0.0]},
                    "area": 0.0015,
                },
                {
                    "id": "JBIJ",
                    "surface": {"type": "cylinder", "origin": [0.0, 0.0, 0.0]},
                    "area": 0.0009,
                },
            ],
            "edges": [
                {"id": "JHO", "geometry": {"type": "line", "length": 0.030}},
                {"id": "JHP", "geometry": {"type": "circle", "length": 0.012}},
            ],
        }
    ],
    "microversionId": "mv-abc",
}

#: GET /api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/features — with real parameter
#: objects, which is what a surgical edit clones.
FEATURE_TREE_WITH_PARAMETERS = {
    "features": [
        {
            "btType": "BTMFeature-134",
            "message": {
                "name": "Extrude 1",
                "featureId": "F2",
                "featureType": "extrude",
                "parameters": [
                    {
                        "btType": "BTMParameterQuantity-147",
                        "parameterId": "depth",
                        "expression": "10 mm",
                    },
                    {
                        "btType": "BTMParameterBoolean-144",
                        "parameterId": "oppositeDirection",
                        "value": False,
                    },
                    {
                        "btType": "BTMParameterQueryList-148",
                        "parameterId": "entities",
                        "queries": [
                            {
                                "btType": "BTMIndividualQuery-138",
                                "deterministicIds": ["JBIH"],
                            }
                        ],
                    },
                ],
            },
        },
        {
            "btType": "BTMFeature-134",
            "message": {
                "name": "Fillet 1",
                "featureId": "F3",
                "featureType": "fillet",
                "parameters": [
                    # An EMPTY query: there is no example object to clone, so a
                    # geometry change here must be refused, not invented.
                    {
                        "btType": "BTMParameterQueryList-148",
                        "parameterId": "entities",
                        "queries": [],
                    }
                ],
            },
        },
    ],
    "serializationVersion": "1.2.7",
    "sourceMicroversion": "mv-abc",
    "libraryVersion": 2522,
}
