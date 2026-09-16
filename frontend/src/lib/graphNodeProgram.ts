/* Custom sigma node program for the knowledge-graph canvas.

   The stock NodeCircleProgram draws one flat disc. The graph's visual
   contract needs two colour axes on every node:

     · fill   = entity type   (a_color, per node)
     · ring   = review status → solid ring for 승인됨, dashed ring for 검토 대기

   plus two interaction states:

     · selected → point-coloured halo outside the disc (data state is never
       painted over, matching the retired SVG renderer)
     · search-dimmed → alpha drop on the whole node

   Ring colour arrives as an attribute (a_ringColor); dashed/dimmed pack into
   a single float flag (bit 0 = dashed, bit 1 = dimmed); the halo colour is an
   attribute too (fully transparent when the node is not selected, so the
   halo pass costs nothing for the common case). Geometry is one triangle
   per node like the stock program — the triangle's inscribed disc is bigger
   than the drawn disc, leaving room for the halo band.

   Attribute layout (8 floats / vertex):
     a_position(2) a_size(1) a_color(4B) a_id(4B) a_ringColor(4B)
     a_haloColor(4B) a_flags(1)                                       */

import { NodeProgram } from "sigma/rendering";
import type { ProgramInfo } from "sigma/rendering";
import type { NodeDisplayData, RenderParams } from "sigma/types";
import type { Attributes } from "graphology-types";
import { floatColor } from "sigma/utils";

// language=GLSL
const VERTEX_SHADER_SOURCE = /*glsl*/ `
attribute vec4 a_id;
attribute vec4 a_color;
attribute vec4 a_ringColor;
attribute vec4 a_haloColor;
attribute vec2 a_position;
attribute float a_size;
attribute float a_flags;
attribute float a_angle;

uniform mat3 u_matrix;
uniform float u_sizeRatio;
uniform float u_correctionRatio;

varying vec4 v_color;
varying vec4 v_ringColor;
varying vec4 v_haloColor;
varying vec2 v_diffVector;
varying float v_radius;
varying float v_flags;

const float bias = 255.0 / 254.0;

void main() {
  // Drawn disc radius matches the stock program (2 * a_size in display
  // units); the covering triangle is larger so the halo band fits inside
  // its inscribed circle (inscribed radius = 1.45 * drawn).
  float drawn = a_size * u_correctionRatio / u_sizeRatio * 2.0;
  vec2 diffVector = drawn * 2.9 * vec2(cos(a_angle), sin(a_angle));
  vec2 position = a_position + diffVector;
  gl_Position = vec4(
    (u_matrix * vec3(position, 1)).xy,
    0,
    1
  );

  v_diffVector = diffVector;
  v_radius = drawn;
  v_flags = a_flags;

  #ifdef PICKING_MODE
  v_color = a_id;
  #else
  v_color = a_color;
  v_ringColor = a_ringColor;
  v_haloColor = a_haloColor;
  #endif

  v_color.a *= bias;
}
`;

// language=GLSL
const FRAGMENT_SHADER_SOURCE = /*glsl*/ `
precision highp float;

varying vec4 v_color;
varying vec4 v_ringColor;
varying vec4 v_haloColor;
varying vec2 v_diffVector;
varying float v_radius;
varying float v_flags;

uniform float u_correctionRatio;

const vec4 transparent = vec4(0.0, 0.0, 0.0, 0.0);

void main(void) {
  float ring = u_correctionRatio * 2.6;
  float aa = u_correctionRatio * 1.4;
  float dist = length(v_diffVector);
  float r = v_radius;
  float halo = v_radius * 0.30;

  float dashed = mod(v_flags, 2.0);
  float dimmed = step(1.5, v_flags);

  #ifdef PICKING_MODE
  if (dist > r)
    gl_FragColor = transparent;
  else
    gl_FragColor = v_color;

  #else
  vec4 color = transparent;
  if (dist <= r - ring) {
    color = v_color;
  } else if (dist <= r) {
    color = v_ringColor;
    if (dashed > 0.5) {
      // ~6 dashes around the ring, 58% stroke / 42% gap — the same
      // "draft" cue the SVG renderer's stroke-dasharray carried.
      float ang = atan(v_diffVector.y, v_diffVector.x);
      if (fract(ang * 0.954929 + 0.25) < 0.42) color = transparent;
    }
  } else if (dist <= r + halo) {
    color = vec4(v_haloColor.rgb, v_haloColor.a * (1.0 - (dist - r) / halo));
  }

  if (dimmed > 0.5) color.a *= 0.18;
  // Soften the outer silhouette the way the stock AA border does.
  color.a *= 1.0 - smoothstep(r - aa, r, dist);

  gl_FragColor = color;
  #endif
}
`;

const UNIFORMS = ["u_sizeRatio", "u_correctionRatio", "u_matrix"] as const;

interface StatusDisplayData extends NodeDisplayData {
  ringColor?: string;
  haloColor?: string;
  dashed?: boolean;
  dimmed?: boolean;
}

export default class NodeStatusProgram<
  N extends Attributes = Attributes,
  E extends Attributes = Attributes,
  G extends Attributes = Attributes,
> extends NodeProgram<(typeof UNIFORMS)[number], N, E, G> {
  static readonly ANGLE_1 = 0;
  static readonly ANGLE_2 = (2 * Math.PI) / 3;
  static readonly ANGLE_3 = (4 * Math.PI) / 3;

  getDefinition() {
    return {
      VERTICES: 3,
      VERTEX_SHADER_SOURCE,
      FRAGMENT_SHADER_SOURCE,
      METHOD: 4 /* WebGL TRIANGLES */,
      UNIFORMS,
      ATTRIBUTES: [
        { name: "a_position", size: 2, type: 5126 /* FLOAT */ },
        { name: "a_size", size: 1, type: 5126 },
        { name: "a_color", size: 4, type: 5121 /* UNSIGNED_BYTE */, normalized: true },
        { name: "a_id", size: 4, type: 5121, normalized: true },
        { name: "a_ringColor", size: 4, type: 5121, normalized: true },
        { name: "a_haloColor", size: 4, type: 5121, normalized: true },
        { name: "a_flags", size: 1, type: 5126 },
      ],
      CONSTANT_ATTRIBUTES: [{ name: "a_angle", size: 1, type: 5126 }],
      CONSTANT_DATA: [
        [NodeStatusProgram.ANGLE_1],
        [NodeStatusProgram.ANGLE_2],
        [NodeStatusProgram.ANGLE_3],
      ],
    };
  }

  processVisibleItem(nodeIndex: number, startIndex: number, data: NodeDisplayData): void {
    const d = data as StatusDisplayData;
    const array = this.array;
    array[startIndex++] = d.x;
    array[startIndex++] = d.y;
    array[startIndex++] = d.size;
    array[startIndex++] = floatColor(d.color);
    array[startIndex++] = nodeIndex;
    array[startIndex++] = floatColor(d.ringColor ?? "#00000000");
    array[startIndex++] = floatColor(d.haloColor ?? "#00000000");
    array[startIndex] = (d.dashed ? 1 : 0) + (d.dimmed ? 2 : 0);
  }

  setUniforms(params: RenderParams, { gl, uniformLocations }: ProgramInfo): void {
    const { u_sizeRatio, u_correctionRatio, u_matrix } = uniformLocations;
    gl.uniform1f(u_correctionRatio, params.correctionRatio);
    gl.uniform1f(u_sizeRatio, params.sizeRatio);
    gl.uniformMatrix3fv(u_matrix, false, params.matrix);
  }
}
