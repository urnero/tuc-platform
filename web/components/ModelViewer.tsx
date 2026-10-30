"use client";

/**
 * 3D-просмотр загруженной модели (B03).
 * Берёт файл из /api/v1/uploads/{id}/file, показывает в WebGL: вращение мышью, сетка-пол,
 * модель отцентрирована и стоит на полу. Размер сцены подстраивается под модель.
 * Раскраска по частям (B31): partColors красит диапазоны треугольников STL своими цветами,
 * keepMaterials оставляет цвета деталей из 3MF (результат раскраски).
 *
 * Только на клиенте: в page.tsx подключать через next/dynamic с ssr: false.
 */

import { OrbitControls, Grid } from "@react-three/drei";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useMemo } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";

/** Диапазон треугольников STL одного цвета (раскраска по частям, B31). */
export type PartColor = { start: number; count: number; hex: string };

type Props = {
  url: string;
  ext: "stl" | "3mf";
  /** Во сколько раз умножить координаты файла (25.4, если файл в дюймах). */
  scale?: number;
  /** Только для STL: покрасить треугольники по диапазонам (детали модели своими цветами). */
  partColors?: PartColor[];
  /** Только для 3MF: оставить цвета из файла (basematerials), а не красить всё одним. */
  keepMaterials?: boolean;
  height?: number;
};

const MATERIAL = new THREE.MeshStandardMaterial({
  color: "#4fbfb2",
  metalness: 0.1,
  roughness: 0.6,
});

const PAINTED = new THREE.MeshStandardMaterial({
  vertexColors: true,
  metalness: 0.1,
  roughness: 0.6,
});

/** Пишет атрибут color: у STL каждый треугольник — три своих вершины подряд, поэтому
 *  треугольник k — это вершины 3k, 3k+1, 3k+2. Треугольники вне диапазонов — серые. */
export function applyPartColors(geometry: THREE.BufferGeometry, parts: PartColor[]) {
  const n = geometry.getAttribute("position").count;
  const colors = new Float32Array(n * 3).fill(0.5);
  const c = new THREE.Color();
  for (const part of parts) {
    c.set(part.hex);
    const from = part.start * 3;
    const to = Math.min(n, (part.start + part.count) * 3);
    for (let v = from; v < to; v++) {
      colors[v * 3] = c.r;
      colors[v * 3 + 1] = c.g;
      colors[v * 3 + 2] = c.b;
    }
  }
  const attr = geometry.getAttribute("color") as THREE.BufferAttribute | undefined;
  if (attr && attr.count === n) {
    (attr.array as Float32Array).set(colors);
    attr.needsUpdate = true;
  } else {
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  }
}

/** Загружает модель, центрирует её и ставит на «пол» (z = 0 → y = 0 в сцене). */
function Model({ url, ext, scale = 1, partColors, keepMaterials }: Props) {
  // STL → геометрия, 3MF → группа объектов. Приводим к одному виду: Object3D.
  const loaded = useLoader(ext === "stl" ? STLLoader : ThreeMFLoader, url);
  const painted = Boolean(partColors && loaded instanceof THREE.BufferGeometry);

  const { object, size } = useMemo(() => {
    let obj: THREE.Object3D;
    if (loaded instanceof THREE.BufferGeometry) {
      // Перекраска: геометрия та же, меняется только атрибут цвета.
      if (painted && partColors) applyPartColors(loaded, partColors);
      obj = new THREE.Mesh(loaded, painted ? PAINTED : MATERIAL);
    } else {
      obj = loaded as THREE.Group;
      if (!keepMaterials) {
        obj.traverse((child) => {
          if (child instanceof THREE.Mesh) child.material = MATERIAL;
        });
      }
    }
    // В 3D-печати «вверх» — ось Z. В three.js вверх — Y. Поворачиваем модель.
    const wrapper = new THREE.Group();
    wrapper.add(obj);
    wrapper.scale.setScalar(scale);
    wrapper.rotation.x = -Math.PI / 2;

    const box = new THREE.Box3().setFromObject(wrapper);
    const center = box.getCenter(new THREE.Vector3());
    const sz = box.getSize(new THREE.Vector3());
    // Центр в ноль по X/Z, нижняя грань на y = 0.
    wrapper.position.set(-center.x, -box.min.y, -center.z);
    return { object: wrapper, size: sz };
  }, [loaded, scale, painted, partColors, keepMaterials]);

  const longest = Math.max(size.x, size.y, size.z, 1);
  return (
    <>
      <primitive object={object} />
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

/** Ставит камеру так, чтобы модель целиком попала в кадр. */
function CameraFit({ longest }: { longest: number }) {
  const camera = useThree((s) => s.camera);
  const dist = longest * 1.8;
  useEffect(() => {
    // Камера под углом сверху-спереди; пересчитываем, когда меняется размер модели.
    camera.position.set(dist, dist * 0.7, dist);
    camera.lookAt(0, longest * 0.25, 0);
    camera.updateProjectionMatrix();
  }, [camera, dist, longest]);
  return (
    <OrbitControls
      makeDefault
      target={[0, longest * 0.25, 0]}
      minDistance={longest * 0.3}
      maxDistance={dist * 5}
    />
  );
}

export default function ModelViewer(props: Props) {
  return (
    <div
      className="w-full overflow-hidden rounded-lg border"
      style={{ borderColor: "var(--ink-muted)", height: props.height ?? 420 }}
    >
      <Canvas camera={{ fov: 45, near: 0.1, far: 100000 }}>
        <color attach="background" args={["#1a2220"]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[1, 2, 1]} intensity={1.2} />
        <directionalLight position={[-2, 1, -1]} intensity={0.4} />
        <Suspense fallback={null}>
          <Model {...props} />
        </Suspense>
      </Canvas>
    </div>
  );
}
