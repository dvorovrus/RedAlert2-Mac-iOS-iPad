import * as THREE from 'three';
import { rectContainsPoint } from '../../util/geometry';
import { Coords } from '../../game/Coords';
import { IsoCoords } from '../IsoCoords';
import { isPerformanceFeatureEnabled, measurePerformanceFeature } from '@/performance/PerformanceRuntime';
interface Point {
    x: number;
    y: number;
}
interface Viewport {
    x: number;
    y: number;
    width: number;
    height: number;
}
interface CameraPan {
    getPan(): Point;
}
interface CameraZoom {
    getZoom(): number;
}
interface Scene {
    viewport: Viewport;
    cameraPan: CameraPan;
    cameraZoom?: CameraZoom;
}
interface MapTile {
    rx: number;
    ry: number;
    z: number;
}
interface TileManager {
    getByMapCoords(x: number, y: number): MapTile | undefined;
}
interface GameMap {
    tiles: TileManager;
}
export class MapTileIntersectHelper {
    private map: GameMap;
    private scene: Scene;
    private intersectTriangle?: THREE.Triangle;
    private intersectPoint?: THREE.Vector3;
    private intersectedTilesScratch: MapTile[] = [];
    constructor(map: GameMap, scene: Scene) {
        this.map = map;
        this.scene = scene;
    }
    private collectCandidateTiles(centerTile: MapTile, tileElevation: number): MapTile[] {
        const candidateTiles: MapTile[] = [];
        if (tileElevation) {
            const radius = Math.max(4, Math.ceil(Math.abs(tileElevation)) + 4);
            const seen = new Set<string>();
            for (let dx = -radius; dx <= radius; dx += 1) {
                for (let dy = -radius; dy <= radius; dy += 1) {
                    const tile = this.map.tiles.getByMapCoords(centerTile.rx + dx, centerTile.ry + dy);
                    if (tile) {
                        const key = `${tile.rx},${tile.ry}`;
                        if (!seen.has(key)) {
                            seen.add(key);
                            candidateTiles.push(tile);
                        }
                    }
                }
            }
            return candidateTiles;
        }
        for (let offset = 0; offset < 30; offset++) {
            const testCoords = [
                { x: centerTile.rx + offset, y: centerTile.ry + offset },
                { x: centerTile.rx + offset + 1, y: centerTile.ry + offset },
                { x: centerTile.rx + offset, y: centerTile.ry + offset + 1 }
            ];
            for (const coord of testCoords) {
                const tile = this.map.tiles.getByMapCoords(coord.x, coord.y);
                if (tile) {
                    candidateTiles.push(tile);
                }
            }
        }
        return candidateTiles;
    }
    getTileAtScreenPoint(screenPoint: Point, tileElevation: number = 0): MapTile | undefined {
        const viewport = this.scene.viewport;
        if (rectContainsPoint(viewport, screenPoint)) {
            const intersectedTiles = this.intersectTilesByScreenPos(screenPoint, tileElevation);
            return intersectedTiles.length > 0 ? intersectedTiles[0] : undefined;
        }
        return undefined;
    }
    getTileCenterScreenPoint(tile: MapTile, tileElevation: number = 0): Point {
        const viewport = this.scene.viewport;
        const origin = IsoCoords.worldToScreen(0, 0);
        const pan = this.scene.cameraPan.getPan();
        const zoom = this.scene.cameraZoom?.getZoom() ?? 1;
        const screenPos = IsoCoords.tile3dToScreen(tile.rx + 0.5, tile.ry + 0.5, tile.z + tileElevation);
        const centerX = viewport.x + viewport.width / 2;
        const centerY = viewport.y + viewport.height / 2;
        return {
            x: centerX + (screenPos.x - origin.x - pan.x) * zoom,
            y: centerY + (screenPos.y - origin.y - pan.y) * zoom
        };
    }
    intersectTilesByScreenPos(screenPoint: Point, tileElevation: number = 0): MapTile[] {
        return measurePerformanceFeature('mapTileHitTest', () => isPerformanceFeatureEnabled('mapTileHitTest')
            ? this.intersectTilesByScreenPosOptimized(screenPoint, tileElevation)
            : this.intersectTilesByScreenPosLegacy(screenPoint, tileElevation));
    }
    private intersectTilesByScreenPosLegacy(screenPoint: Point, tileElevation: number = 0): MapTile[] {
        const origin = IsoCoords.worldToScreen(0, 0);
        const pan = this.scene.cameraPan.getPan();
        const viewport = this.scene.viewport;
        const zoom = this.scene.cameraZoom?.getZoom() ?? 1;
        const centerX = viewport.x + viewport.width / 2;
        const centerY = viewport.y + viewport.height / 2;
        const worldScreenPos = {
            x: (screenPoint.x - centerX) / zoom + origin.x + pan.x,
            y: (screenPoint.y - centerY) / zoom + origin.y + pan.y
        };
        const projectedWorldScreenY = worldScreenPos.y + IsoCoords.tileHeightToScreen(tileElevation);
        const worldPos = IsoCoords.screenToWorld(worldScreenPos.x, projectedWorldScreenY);
        const tileCoords = new THREE.Vector2(worldPos.x, worldPos.y)
            .multiplyScalar(1 / Coords.LEPTONS_PER_TILE)
            .floor();
        const centerTile = this.map.tiles.getByMapCoords(tileCoords.x, tileCoords.y);
        if (!centerTile) {
            console.warn(`Tile coordinates (${tileCoords.x},${tileCoords.y}) out of range`);
            return [];
        }
        const candidateTiles = this.collectCandidateTiles(centerTile, tileElevation);
        const intersectedTiles: MapTile[] = [];
        const triangle = new THREE.Triangle();
        const testPoint = new THREE.Vector3(worldScreenPos.x, 0, worldScreenPos.y);
        for (const tile of candidateTiles) {
            const testHeight = tile.z + tileElevation;
            const corner1 = IsoCoords.tile3dToScreen(tile.rx, tile.ry, testHeight);
            const corner2 = IsoCoords.tile3dToScreen(tile.rx, tile.ry + 1.1, testHeight);
            const corner3 = IsoCoords.tile3dToScreen(tile.rx + 1.1, tile.ry, testHeight);
            const corner4 = IsoCoords.tile3dToScreen(tile.rx + 1.1, tile.ry + 1.1, testHeight);
            triangle.a.set(corner1.x, 0, corner1.y);
            triangle.b.set(corner2.x, 0, corner2.y);
            triangle.c.set(corner3.x, 0, corner3.y);
            const intersects1 = triangle.containsPoint(testPoint);
            triangle.a.set(corner4.x, 0, corner4.y);
            triangle.b.set(corner2.x, 0, corner2.y);
            triangle.c.set(corner3.x, 0, corner3.y);
            const intersects2 = triangle.containsPoint(testPoint);
            if (intersects1 || intersects2) {
                intersectedTiles.unshift(tile);
            }
        }
        if (intersectedTiles.length === 0) {
            return this.intersectTilesByScreenPosLegacy({
                x: screenPoint.x,
                y: screenPoint.y - IsoCoords.tileHeightToScreen(1) * (this.scene.cameraZoom?.getZoom() ?? 1)
            }, tileElevation);
        }
        return intersectedTiles;
    }
    private intersectTilesByScreenPosOptimized(screenPoint: Point, tileElevation: number = 0): MapTile[] {
        const triangle = this.intersectTriangle ?? (this.intersectTriangle = new THREE.Triangle());
        const testPoint = this.intersectPoint ?? (this.intersectPoint = new THREE.Vector3());
        const intersectedTiles = this.intersectedTilesScratch;
        const origin = IsoCoords.worldToScreen(0, 0);
        const pan = this.scene.cameraPan.getPan();
        const viewport = this.scene.viewport;
        const zoom = this.scene.cameraZoom?.getZoom() ?? 1;
        const centerX = viewport.x + viewport.width / 2;
        const centerY = viewport.y + viewport.height / 2;
        const fallbackOffsetY = IsoCoords.tileHeightToScreen(1) * zoom;
        let currentY = screenPoint.y;
        for (let attempt = 0; attempt < 4; attempt += 1) {
            intersectedTiles.length = 0;
            const worldScreenX = (screenPoint.x - centerX) / zoom + origin.x + pan.x;
            const worldScreenY = (currentY - centerY) / zoom + origin.y + pan.y;
            const projectedWorldScreenY = worldScreenY + IsoCoords.tileHeightToScreen(tileElevation);
            const worldPos = IsoCoords.screenToWorld(worldScreenX, projectedWorldScreenY);
            const tileX = Math.floor(worldPos.x / Coords.LEPTONS_PER_TILE);
            const tileY = Math.floor(worldPos.y / Coords.LEPTONS_PER_TILE);
            const centerTile = this.map.tiles.getByMapCoords(tileX, tileY);
            if (!centerTile) {
                console.warn(`Tile coordinates (${tileX},${tileY}) out of range`);
                return [];
            }
            testPoint.set(worldScreenX, 0, worldScreenY);
            for (const tile of this.collectCandidateTiles(centerTile, tileElevation)) {
                    const testHeight = tile.z + tileElevation;
                    const corner1 = IsoCoords.tile3dToScreen(tile.rx, tile.ry, testHeight);
                    const corner2 = IsoCoords.tile3dToScreen(tile.rx, tile.ry + 1.1, testHeight);
                    const corner3 = IsoCoords.tile3dToScreen(tile.rx + 1.1, tile.ry, testHeight);
                    const corner4 = IsoCoords.tile3dToScreen(tile.rx + 1.1, tile.ry + 1.1, testHeight);
                    triangle.a.set(corner1.x, 0, corner1.y);
                    triangle.b.set(corner2.x, 0, corner2.y);
                    triangle.c.set(corner3.x, 0, corner3.y);
                    const intersects1 = triangle.containsPoint(testPoint);
                    triangle.a.set(corner4.x, 0, corner4.y);
                    triangle.b.set(corner2.x, 0, corner2.y);
                    triangle.c.set(corner3.x, 0, corner3.y);
                    const intersects2 = triangle.containsPoint(testPoint);
                    if (intersects1 || intersects2) {
                        intersectedTiles.unshift(tile);
                    }
            }
            if (intersectedTiles.length > 0) {
                return [...intersectedTiles];
            }
            currentY -= fallbackOffsetY;
        }
        return [];
    }
}
