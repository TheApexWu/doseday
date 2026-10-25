# Model doseday:cloud-pill-vision:cloud-pill-detector

This Vision service proxies Viam camera frames to the DoseDay pill detector on
a Brev GPU. It exposes a detection only when the remote pipeline finds exactly
one pill matching the selected primary color and shape.

## Configuration

```json
{
  "camera_name": "follower-cam",
  "endpoint": "https://YOUR-BREV-ENDPOINT/api/detect",
  "timeout_seconds": 30
}
```

| Name | Type | Inclusion | Description |
|---|---|---|---|
| `camera_name` | string | Required | Viam camera used for live frames. |
| `endpoint` | string | Required | Brev `/api/detect` HTTP(S) endpoint. |
| `timeout_seconds` | number | Optional | Remote inference timeout; default 30, maximum 120. |

The endpoint must be reachable from the machine running the module. If it
requires a bearer token, provide it to the module process as
`BREV_API_TOKEN`; never place the token in machine JSON.

## DoCommand

Select the pill that the service should expose:

```json
{
  "command": "set_target",
  "primary_color": "white",
  "shape": "round"
}
```

Read or clear the current target:

```json
{"command": "get_target"}
```

```json
{"command": "clear_target"}
```

The service returns no boxes when the target is unset, when no pill matches,
or when multiple pills match. This prevents downstream robot logic from
selecting an arbitrary pill.
