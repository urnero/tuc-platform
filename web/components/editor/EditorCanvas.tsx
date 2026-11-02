"use client";

/**
 * 3D-окно интерактивного редактора (B60, docs/EDITOR.md).
 *
 * Показывает модель клиента (как ModelViewer: Z файла → Y сцены, модель стоит на полу по центру)
 * и поверх неё наложения из хранилища редактора (lib/editor/store.ts):
 *  - курсор над моделью → raycast даёт точку и нормаль → плашка-предпросмотр «прилипает»
 *    к поверхности (действие hover);
 *  - клик / тап по модели → наложение ставится в эту точку (действие place);
 *  - выбранное наложение держит гизмо TransformControls: «двигать» — в касательной плоскости,
 *    после каждого сдвига плашка снова прилипает к поверхности (raycast вдоль нормали);
 *    за краем грани — переезжает на соседнюю грань под курсором (B60a «за угол»);
 *    «повернуть» — только вокруг нормали (меняется вектор «верх»); «размер» — меняет size_mm.
 *
 * Надпись — живой 3D-текст (B61, lib/editor/text3d.ts): шрифт Liberation как на сервере,
 * обновляется при каждой правке в панели. Пока шрифт грузится, пустой текст или логотип (B62) —
 * плашка-прямоугольник. Выбранную надпись можно тянуть прямо пальцем/мышью по поверхности,
 * а на телефоне — растягивать щипком двумя пальцами.
 * Только на клиенте: подключать через next/dynamic с ssr: false.
 */

import { Grid, OrbitControls, TransformControls } from "@react-three/drei";
import { Canvas, type ThreeEvent, useLoader, useThree } from "@react-three/fiber";
import { FontLoader } from "three/examples/jsm/loaders/FontLoader.js";
import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import {
  makePlacement,
  modelDirToScene,
  type Placement,
  placementSceneMatrix,
  type SceneFit,
  sceneDirToModel,
  sceneToModel,
  textWidthMm,
  transportUp,
  type Vec3,
} from "@/lib/editor/math";
import { gizmoSize, useIsPhone } from "@/lib/editor/phone";
import { buildTextGeometry, pinchSize, typefaceUrl } from "@/lib/editor/text3d";
import { type EditorStore, type Overlay, type OverlayDraft, useEditor } from "@/lib/editor/store";

type Props = {
  url: string;
  ext: "stl" | "3mf";
  /** Во сколько раз умножить координаты файла (25.4, если файл в дюймах). */
  scale?: number;
  store: EditorStore;
};

const MATERIAL = new THREE.MeshStandardMaterial({ color: "#4fbfb2", metalness: 0.1, roughness: 0.6 });
/** Как показать наложение: стоит на модели / выбрано / предпросмотр под курсором. */
type Role = "static" | "selected" | "ghost";

/**
 * Материал надписи. Выпукло — цвет просмотра из панели; врезано — полупрозрачный красный
 * («здесь будет вырез»); выбранная подсвечена; предпросмотр под курсором — полупрозрачный.
 */
function useOverlayMaterial(role: Role, mode: OverlayDraft["mode"], color: string): THREE.Material {
  const material = useMemo(() => {
    const engraved = mode === "engraved";
    const m = new THREE.MeshStandardMaterial({ color: engraved ? "#c0392b" : color, roughness: 0.5 });
    if (engraved) {
      m.transparent = true;
      m.opacity = 0.8;
    }
    if (role === "selected") {
      // Подсветка выбранной — чуть светлее, цвет просмотра не искажаем.
      m.emissive = new THREE.Color("#ffffff");
      m.emissiveIntensity = 0.12;
    }
    if (role === "ghost") {
      m.transparent = true;
      m.opacity = 0.45;
      m.depthWrite = false;
    }
    return m;
  }, [role, mode, color]);
  useEffect(() => () => material.dispose(), [material]);
  return material;
}

const v3 = (v: Vec3) => new THREE.Vector3(v[0], v[1], v[2]);
const arr = (v: THREE.Vector3): Vec3 => [v.x, v.y, v.z];

/** Точка и нормаль попадания (мировые координаты сцены) → размещение в системе модели. */
function hitToPlacement(point: THREE.Vector3, face: THREE.Face | null | undefined, object: THREE.Object3D, fit: SceneFit, upHint?: Vec3): Placement | null {
  if (!face) return null;
  const normal = face.normal.clone().transformDirection(object.matrixWorld);
  return makePlacement(sceneToModel(arr(point), fit), sceneDirToModel(arr(normal)), upHint);
}

/** Плашка наложения в его локальной системе: X — вправо, Y — верх букв, Z — наружу. */
function Plaque({ draft, material }: { draft: OverlayDraft; material: THREE.Material }) {
  const w = draft.kind === "text" ? textWidthMm(draft.text, draft.size_mm) : draft.size_mm;
  const h = draft.size_mm;
  const d = draft.depth_mm;
  const z = draft.mode === "engraved" ? -d / 2 : d / 2;
  return (
    <group>
      <mesh position={[0, 0, z]} material={material}>
        <boxGeometry args={[w, h, d]} />
      </mesh>
      {/* Стрелка «верх» — чтобы было видно, куда смотрят буквы, пока текста нет (B61). */}
      <mesh position={[0, h / 2 + h * 0.15, Math.max(z, 0) + 0.05]} material={material}>
        <coneGeometry args={[h * 0.1, h * 0.25, 12]} />
      </mesh>
    </group>
  );
}

/** Живой 3D-текст: геометрия пересобирается при каждой правке текста, шрифта, размера, глубины. */
function LiveText({ draft, material }: { draft: OverlayDraft; material: THREE.Material }) {
  const font = useLoader(FontLoader, typefaceUrl(draft.font, draft.bold));
  const geometry = useMemo(
    () => buildTextGeometry(font, draft.text, draft.size_mm, draft.depth_mm, draft.mode),
    [font, draft.text, draft.size_mm, draft.depth_mm, draft.mode],
  );
  useEffect(() => () => geometry?.dispose(), [geometry]);
  if (!geometry) return <Plaque draft={draft} material={material} />;
  return <mesh geometry={geometry} material={material} />;
}

/** Тело наложения: надпись — 3D-текст (пока грузится шрифт — плашка), логотип — плашка (до B62). */
function OverlayBody({ draft, role, color }: { draft: OverlayDraft; role: Role; color: string }) {
  const material = useOverlayMaterial(role, draft.mode, color);
  if (draft.kind !== "text" || !draft.text.trim()) return <Plaque draft={draft} material={material} />;
  return (
    <Suspense fallback={<Plaque draft={draft} material={material} />}>
      <LiveText draft={draft} material={material} />
    </Suspense>
  );
}

/** Наложение, стоящее на модели без гизмо: матрица из размещения. */
function StaticOverlay({ overlay, fit, store, color }: { overlay: Overlay; fit: SceneFit; store: EditorStore; color: string }) {
  const matrix = useMemo(
    () => new THREE.Matrix4().fromArray(placementSceneMatrix(overlay.placement, fit)),
    [overlay.placement, fit],
  );
  return (
    <group
      matrix={matrix}
      matrixAutoUpdate={false}
      onClick={(e) => {
        if (e.delta > 5) return;
        e.stopPropagation();
        store.dispatch({ type: "select", id: overlay.id });
      }}
    >
      <OverlayBody draft={overlay} role="static" color={color} />
    </group>
  );
}

/** Выбранное наложение с гизмо. */
function SelectedOverlay({
  overlay,
  fit,
  store,
  target,
  longest,
  dragging,
  color,
}: {
  overlay: Overlay;
  color: string;
  fit: SceneFit;
  store: EditorStore;
  target: THREE.Object3D;
  longest: number;
  /** Флаг «тянут гизмо»: клик по модели в этот момент не снимает выбор. */
  dragging: MutableRefObject<boolean>;
}) {
  const group = useRef<THREE.Group>(null!);
  /** Внутренняя группа: поворот плашки на новой грани во время перетаскивания (B60a). */
  const inner = useRef<THREE.Group>(null!);
  const gizmo = useEditor(store, (s) => s.gizmo);
  /** На телефоне гизмо крупнее — под палец (B60b). */
  const phone = useIsPhone();
  const raycaster = useMemo(() => new THREE.Raycaster(), []);
  const lastSnap = useRef<Placement | null>(null);

  // Группа стоит там, где размещение; после каждого изменения размещения — заново.
  // Во время перетаскивания (duringDrag) саму группу не трогаем: её двигает TransformControls,
  // и от её положения он считает плоскость перетаскивания — если переставить группу на другую
  // грань (B60a «за угол»), гизмо начнёт прыгать. Поэтому плашку на поверхность ставит
  // внутренняя группа (inner = группа⁻¹ × размещение), а группа догоняет её на отпускании.
  const applyPlacement = useCallback(
    (p: Placement, duringDrag = false) => {
      const m = new THREE.Matrix4().fromArray(placementSceneMatrix(p, fit));
      if (duringDrag) {
        group.current.updateMatrix();
        const local = group.current.matrix.clone().invert().multiply(m);
        local.decompose(inner.current.position, inner.current.quaternion, inner.current.scale);
        return;
      }
      group.current.position.setFromMatrixPosition(m);
      group.current.quaternion.setFromRotationMatrix(m);
      group.current.scale.setScalar(1);
      inner.current.position.set(0, 0, 0);
      inner.current.quaternion.identity();
      inner.current.scale.setScalar(1);
    },
    [fit],
  );
  useLayoutEffect(() => applyPlacement(overlay.placement), [overlay.placement, applyPlacement]);

  const { camera, gl } = useThree();
  // Курсор в координатах −1…1 (NDC). Свой слушатель, а не useThree().pointer: пока тянут
  // гизмо, TransformControls захватывает указатель и pointer в состоянии r3f не обновляется.
  const pointer = useMemo(() => new THREE.Vector2(), []);
  useEffect(() => {
    const el = gl.domElement;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    };
    el.addEventListener("pointermove", onMove, true);
    el.addEventListener("pointerdown", onMove, true);
    return () => {
      el.removeEventListener("pointermove", onMove, true);
      el.removeEventListener("pointerdown", onMove, true);
    };
  }, [gl, pointer]);

  /**
   * Где поверхность под текущим положением группы.
   * 1) Луч вдоль нормали (той, что была в начале перетаскивания) туда и обратно — обычный
   *    сдвиг по грани.
   * 2) Не попал — плашку вытащили за край грани (B60a «за угол»): луч из камеры через курсор,
   *    ближайшее попадание по модели. Так надпись переезжает на соседнюю грань, а «верх»
   *    перегибается через ребро (transportUp) и буквы не переворачиваются.
   */
  const snap = useCallback((pos: THREE.Vector3): Placement | null => {
    const start = overlay.placement;
    const n = v3(modelDirToScene(start.normal));
    const far = longest * 4;
    const tryDir = (origin: THREE.Vector3, dir: THREE.Vector3) => {
      raycaster.set(origin, dir);
      raycaster.far = far;
      const hit = raycaster.intersectObject(target, true)[0];
      return hit ? hitToPlacement(hit.point, hit.face, hit.object, fit, start.up) : null;
    };
    const lift = longest * 2;
    const along =
      tryDir(pos.clone().addScaledVector(n, lift), n.clone().negate()) ??
      tryDir(pos.clone().addScaledVector(n, -lift), n);
    if (along) return along;

    raycaster.setFromCamera(pointer, camera);
    raycaster.far = Infinity;
    const hit = raycaster.intersectObject(target, true)[0];
    const p = hit ? hitToPlacement(hit.point, hit.face, hit.object, fit) : null;
    if (!p) return null;
    const prev = lastSnap.current ?? start;
    return makePlacement(p.point, p.normal, transportUp(prev.up, prev.normal, p.normal));
  }, [camera, fit, longest, overlay.placement, pointer, raycaster, target]);

  // --- Тянуть надпись прямо пальцем / мышью (B61) и щипок двумя пальцами на телефоне ---
  const gizmoRef = useRef<{ dragging?: boolean } | null>(null);
  const controls = useThree((s) => s.controls) as { enabled: boolean } | null;
  const direct = useRef<{ pointers: Map<number, { x: number; y: number }>; pinch: { dist: number; size: number } | null } | null>(null);

  const endDirect = useCallback(() => {
    if (!direct.current) return;
    direct.current = null;
    if (controls) controls.enabled = true;
    setTimeout(() => (dragging.current = false), 0);
    const p = lastSnap.current;
    if (p) {
      applyPlacement(p);
      store.dispatch({ type: "move", id: overlay.id, placement: p });
    }
  }, [applyPlacement, controls, dragging, overlay.id, store]);

  useEffect(() => {
    const el = gl.domElement;
    const dist = (m: Map<number, { x: number; y: number }>) => {
      const [a, b] = [...m.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    const onDown = (e: PointerEvent) => {
      const d = direct.current;
      if (!d) return;
      d.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      // Второй палец, пока первый держит надпись, — щипок: меняем размер букв.
      if (d.pointers.size === 2) d.pinch = { dist: dist(d.pointers), size: overlay.size_mm };
    };
    const onMove = (e: PointerEvent) => {
      const d = direct.current;
      if (!d || !d.pointers.has(e.pointerId)) return;
      // Тянут стрелку гизмо — это его перетаскивание, не наше.
      if (gizmoRef.current?.dragging) {
        direct.current = null;
        if (controls) controls.enabled = true;
        return;
      }
      d.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (d.pinch && d.pointers.size >= 2) {
        const size = pinchSize(d.pinch.size, d.pinch.dist, dist(d.pointers));
        if (size !== overlay.size_mm) store.dispatch({ type: "update", id: overlay.id, patch: { size_mm: size } });
        return;
      }
      if (d.pinch) return; // один палец отпустили после щипка — не прыгаем
      // Один палец / мышь: надпись под курсором, «верх» перегибается через рёбра.
      raycaster.setFromCamera(pointer, camera);
      raycaster.far = Infinity;
      const hit = raycaster.intersectObject(target, true)[0];
      const p = hit ? hitToPlacement(hit.point, hit.face, hit.object, fit) : null;
      if (!p) return;
      const prev = lastSnap.current ?? overlay.placement;
      const next = makePlacement(p.point, p.normal, transportUp(prev.up, prev.normal, p.normal));
      lastSnap.current = next;
      applyPlacement(next);
    };
    const onUp = (e: PointerEvent) => {
      const d = direct.current;
      if (!d || !d.pointers.has(e.pointerId)) return;
      d.pointers.delete(e.pointerId);
      if (d.pointers.size === 0) endDirect();
    };
    el.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [applyPlacement, camera, controls, endDirect, fit, gl, overlay.id, overlay.placement, overlay.size_mm, pointer, raycaster, store, target]);

  const startDirect = (e: ThreeEvent<PointerEvent>) => {
    if (gizmoRef.current?.dragging || direct.current) return;
    e.stopPropagation();
    dragging.current = true;
    lastSnap.current = null;
    if (controls) controls.enabled = false; // камера не крутится, пока тянем надпись
    direct.current = { pointers: new Map([[e.pointerId, { x: e.clientX, y: e.clientY }]]), pinch: null };
  };

  const onChange = () => {
    // Во время перетаскивания плашка не отрывается от поверхности: каждый сдвиг — прилипание.
    if (gizmo !== "translate") return;
    // Позиция группы — та, что посчитал гизмо: сдвиг в касательной плоскости начала
    // перетаскивания. Курсор ушёл с модели совсем — плашка остаётся на последней точке.
    const p = snap(group.current.position.clone()) ?? lastSnap.current;
    if (p) {
      lastSnap.current = p;
      applyPlacement(p, true);
    }
  };

  const onMouseUp = () => {
    // Сбрасываем флаг после того, как отработает click этого же события.
    setTimeout(() => (dragging.current = false), 0);
    const g = group.current;
    if (gizmo === "translate") {
      // Последнее прилипание во время перетаскивания и есть итог.
      const p = lastSnap.current ?? overlay.placement;
      applyPlacement(p);
      store.dispatch({ type: "move", id: overlay.id, placement: p });
    } else if (gizmo === "rotate") {
      // Локальная ось Y группы — новый «верх» (в сцене) → в систему модели.
      const upScene = new THREE.Vector3(0, 1, 0).applyQuaternion(g.quaternion);
      const p = makePlacement(overlay.placement.point, overlay.placement.normal, sceneDirToModel(arr(upScene)));
      applyPlacement(p);
      store.dispatch({ type: "move", id: overlay.id, placement: p });
    } else {
      const k = Math.max(g.scale.x, g.scale.y, g.scale.z);
      g.scale.setScalar(1);
      if (Number.isFinite(k) && k > 0) store.dispatch({ type: "update", id: overlay.id, patch: { size_mm: Math.round(overlay.size_mm * k * 10) / 10 } });
    }
  };

  return (
    <>
      <group
        ref={group}
        onPointerDown={startDirect}
        onClick={(e) => e.stopPropagation() /* нажатие на выбранную надпись не снимает выбор */}
      >
        <group ref={inner}>
          <OverlayBody draft={overlay} role="selected" color={color} />
        </group>
      </group>
      <TransformControls
        ref={gizmoRef as never}
        object={group}
        mode={gizmo}
        space="local"
        size={gizmoSize(phone)}
        showZ={gizmo !== "translate"}
        showX={gizmo !== "rotate"}
        showY={gizmo !== "rotate"}
        onMouseDown={() => {
          dragging.current = true;
          lastSnap.current = null;
        }}
        onObjectChange={onChange}
        onMouseUp={onMouseUp}
      />
    </>
  );
}

/** Модель + наложения + обработка курсора. */
function Scene({ url, ext, scale = 1, store }: Props) {
  const loaded = useLoader(ext === "stl" ? STLLoader : ThreeMFLoader, url);
  const tool = useEditor(store, (s) => s.tool);
  const hover = useEditor(store, (s) => s.hover);
  const draft = useEditor(store, (s) => s.draft);
  const overlays = useEditor(store, (s) => s.overlays);
  const selectedId = useEditor(store, (s) => s.selectedId);
  const color = useEditor(store, (s) => s.previewColor);
  const dragging = useRef(false);

  const { object, fit, longest } = useMemo(() => {
    let obj: THREE.Object3D;
    if (loaded instanceof THREE.BufferGeometry) {
      obj = new THREE.Mesh(loaded, MATERIAL);
    } else {
      obj = loaded as THREE.Group;
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh) child.material = MATERIAL;
      });
    }
    const wrapper = new THREE.Group();
    wrapper.add(obj);
    wrapper.scale.setScalar(scale);
    wrapper.rotation.x = -Math.PI / 2;
    const box = new THREE.Box3().setFromObject(wrapper);
    const center = box.getCenter(new THREE.Vector3());
    const sz = box.getSize(new THREE.Vector3());
    wrapper.position.set(-center.x, -box.min.y, -center.z);
    wrapper.updateMatrixWorld(true);
    const f: SceneFit = { offset: [-center.x, -box.min.y, -center.z] };
    return { object: wrapper, fit: f, longest: Math.max(sz.x, sz.y, sz.z, 1) };
  }, [loaded, scale]);

  const placing = tool === "text" || tool === "logo";

  const hoverMatrix = useMemo(
    () => (hover ? new THREE.Matrix4().fromArray(placementSceneMatrix(hover, fit)) : null),
    [hover, fit],
  );

  return (
    <>
      <primitive
        object={object}
        onPointerMove={(e: ThreeEvent<PointerEvent>) => {
          if (!placing || selectedId) return;
          e.stopPropagation();
          store.dispatch({ type: "hover", placement: hitToPlacement(e.point, e.face, e.object, fit) });
        }}
        onPointerOut={() => store.dispatch({ type: "hover", placement: null })}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          if (e.delta > 5 || dragging.current) return; // поворот камеры или гизмо — не клик
          e.stopPropagation();
          if (selectedId) {
            store.dispatch({ type: "select", id: null });
            return;
          }
          if (!placing) return;
          const p = hitToPlacement(e.point, e.face, e.object, fit);
          if (p) store.dispatch({ type: "place", placement: p });
        }}
      />
      {hoverMatrix && hover && (
        <group matrix={hoverMatrix} matrixAutoUpdate={false}>
          <OverlayBody draft={draft} role="ghost" color={color} />
        </group>
      )}
      {overlays.map((o) =>
        o.id === selectedId ? (
          <SelectedOverlay key={o.id} overlay={o} fit={fit} store={store} target={object} longest={longest} dragging={dragging} color={color} />
        ) : (
          <StaticOverlay key={o.id} overlay={o} fit={fit} store={store} color={color} />
        ),
      )}
      <Grid
        args={[longest * 4, longest * 4]}
        cellSize={longest > 100 ? 50 : longest > 20 ? 10 : 1}
        sectionSize={longest > 100 ? 100 : longest > 20 ? 50 : 10}
        cellColor="#7a8a84"
        sectionColor="#4fbfb2"
        fadeDistance={longest * 6}
        infiniteGrid
      />
      <CameraFit longest={longest} />
    </>
  );
}

/** Камера так, чтобы модель целиком попала в кадр (как в ModelViewer). */
function CameraFit({ longest }: { longest: number }) {
  const camera = useThree((s) => s.camera);
  const dist = longest * 1.8;
  useEffect(() => {
    camera.position.set(dist, dist * 0.7, dist);
    camera.lookAt(0, longest * 0.25, 0);
    camera.updateProjectionMatrix();
  }, [camera, dist, longest]);
  return <OrbitControls makeDefault target={[0, longest * 0.25, 0]} minDistance={longest * 0.3} maxDistance={dist * 5} />;
}

export default function EditorCanvas(props: Props) {
  return (
    <Canvas camera={{ fov: 45, near: 0.1, far: 100000 }} style={{ touchAction: "none" }} data-testid="editor-canvas">
      <color attach="background" args={["#1a2220"]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[1, 2, 1]} intensity={1.2} />
      <directionalLight position={[-2, 1, -1]} intensity={0.4} />
      <Suspense fallback={null}>
        <Scene {...props} />
      </Suspense>
    </Canvas>
  );
}
