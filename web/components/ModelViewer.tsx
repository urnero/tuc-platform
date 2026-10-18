"use client";

/**
 * 3D-просмотр загруженной модели (B03).
 * Берёт файл из /api/v1/uploads/{id}/file, показывает в WebGL: вращение мышью, сетка-пол,
 * модель отцентрирована и стоит на полу. Размер сцены подстраивается под модель.
 *
 * Только на клиенте: в page.tsx подключать через next/dynamic с ssr: false.
 */

import { OrbitControls, Grid } from "@react-three/drei";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useMemo } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";

type Props = {
  url: string;
  ext: "stl" | "3mf";
  /** Во сколько раз умножить координаты файла (25.4, если файл в дюймах). */
  scale?: number;
};

const MATERIAL = new THREE.MeshStandardMaterial({
  color: "#4fbfb2",
  metalness: 0.1,
  roughness: 0.6,
});

/** Загружает модель, центрирует её и ставит на «пол» (z = 0 → y = 0 в сцене). */
function Model({ url, ext, scale = 1 }: Props) {
  // STL → геометрия, 3MF → группа объектов. Приводим к одному виду: Object3D.
  const loaded = useLoader(ext === "stl" ? STLLoader : ThreeMFLoader, url);

  const { object, size } = useMemo(() => {
    let obj: THREE.Object3D;
    if (loaded instanceof THREE.BufferGeometry) {
      obj = new THREE.Mesh(loaded, MATERIAL);
    } else {
      obj = loaded as THREE.Group;
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh) child.material = MATERIAL;
      });
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
  }, [loaded, scale]);

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
    <div className="h-[420px] w-full overflow-hidden rounded-lg border" style={{ borderColor: "var(--muted)" }}>
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
