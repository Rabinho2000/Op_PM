import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { useEffect, useRef } from "react";
import type { MapAttention, MapData } from "../api/client";
import { removeMapLayers } from "./mapLayerCleanup";
import {
  buildProjectLocationPopup,
  groupCoincidentProjects,
  PROJECT_CLUSTER_OPTIONS,
  type LocatedProject,
} from "./projectMarkerGroups";

type MapLayer = "projects" | "suppliers" | "pickups" | "issues";

export interface MapItem {
  key: string;
  layer: MapLayer;
  lat: number;
  lon: number;
  title: string;
  onClick: () => void;
  attention?: MapAttention;
  lifecycleStatus?: string | null;
  projectId?: string;
  projectName?: string;
  projectStatus?: string;
}

const ATTENTION_MARKER_CLASSES: Record<MapAttention, string> = {
  green: "map-marker--attention-green",
  yellow: "map-marker--attention-yellow",
  red: "map-marker--attention-red",
};

const ATTENTION_CLUSTER_CLASSES: Record<MapAttention, string> = {
  green: "map-cluster--attention-green",
  yellow: "map-cluster--attention-yellow",
  red: "map-cluster--attention-red",
};

const ATTENTION_RANK: Record<MapAttention, number> = { green: 0, yellow: 1, red: 2 };

export function makeDivIcon(layer: MapLayer, attention?: MapAttention, lifecycleStatus?: string | null): L.DivIcon {
  const attentionClass = layer === "projects" && attention ? ` ${ATTENTION_MARKER_CLASSES[attention]}` : "";
  const lifecycleClass =
    layer === "projects" && (lifecycleStatus === "preparacao" || lifecycleStatus === "construcao")
      ? ` map-marker--lifecycle-${lifecycleStatus}`
      : "";
  return L.divIcon({
    className: "map-marker-host",
    html: `<span class="map-marker map-marker--${layer}${attentionClass}${lifecycleClass}" aria-hidden="true"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

export function clusterIcon(cluster: L.MarkerCluster): L.DivIcon {
  let worst: MapAttention | null = null;
  const lifecycleStatuses = new Set<string>();
  for (const marker of cluster.getAllChildMarkers()) {
    const options = marker.options as { attention?: MapAttention; lifecycleStatus?: string | null };
    if (options.attention && (worst === null || ATTENTION_RANK[options.attention] > ATTENTION_RANK[worst])) {
      worst = options.attention;
    }
    if (options.lifecycleStatus === "preparacao" || options.lifecycleStatus === "construcao") {
      lifecycleStatuses.add(options.lifecycleStatus);
    }
  }
  const clusterClass = worst
    ? ATTENTION_CLUSTER_CLASSES[worst]
    : lifecycleStatuses.size > 1
      ? "map-cluster--lifecycle-mixed"
      : lifecycleStatuses.has("construcao")
        ? "map-cluster--lifecycle-construcao"
        : lifecycleStatuses.has("preparacao")
          ? "map-cluster--lifecycle-preparacao"
          : ATTENTION_CLUSTER_CLASSES.green;
  return L.divIcon({
    className: "map-cluster-host",
    html: `<span class="map-cluster ${clusterClass}"><span class="map-cluster__count">${cluster.getChildCount()}</span></span>`,
    iconSize: [34, 34],
  });
}

export default function ProjectMapView({
  items,
  config,
  height = 480,
  clusterProjects = true,
}: {
  items: MapItem[];
  config: MapData["config"];
  height?: number;
  clusterProjects?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<L.Layer[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;
    const map = L.map(containerRef.current, { scrollWheelZoom: true }).setView([39.6, -8.0], 7);
    L.tileLayer(config.tile_url, { attribution: config.tile_attribution, maxZoom: 19 }).addTo(map);
    mapRef.current = map;
    return () => {
      removeMapLayers(layersRef.current);
      layersRef.current = [];
      map.off();
      map.remove();
      mapRef.current = null;
    };
  }, [config.tile_attribution, config.tile_url]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    removeMapLayers(layersRef.current);
    layersRef.current = [];
    const projectItems: LocatedProject[] = items.flatMap((item) =>
      item.layer === "projects" && item.projectId && item.projectName && item.projectStatus
        ? [{
            key: item.key,
            projectId: item.projectId,
            name: item.projectName,
            status: item.projectStatus,
            lat: item.lat,
            lon: item.lon,
          }]
        : []
    );
    const popupByKey = new Map<string, string>();
    for (const group of groupCoincidentProjects(projectItems)) {
      const popup = buildProjectLocationPopup(group);
      for (const project of group) popupByKey.set(project.key, popup);
    }
    const clusters = clusterProjects
      ? L.markerClusterGroup({ iconCreateFunction: clusterIcon, ...PROJECT_CLUSTER_OPTIONS })
      : null;
    const bounds: L.LatLngExpression[] = [];
    for (const item of items) {
      const marker = L.marker([item.lat, item.lon], {
        icon: makeDivIcon(item.layer, item.attention, item.lifecycleStatus),
        attention: item.attention,
        lifecycleStatus: item.lifecycleStatus,
      } as L.MarkerOptions & { attention?: MapAttention; lifecycleStatus?: string | null }).bindTooltip(item.title);
      const projectPopup = popupByKey.get(item.key);
      if (projectPopup) marker.bindPopup(projectPopup, { maxWidth: 320 });
      else marker.on("click", item.onClick);
      if (item.layer === "projects" && clusters) clusters.addLayer(marker);
      else {
        marker.addTo(map);
        layersRef.current.push(marker);
      }
      bounds.push([item.lat, item.lon]);
    }
    if (clusters) {
      clusters.addTo(map);
      layersRef.current.push(clusters);
    }
    if (bounds.length > 0) map.fitBounds(bounds as L.LatLngBoundsExpression, { padding: [30, 30], maxZoom: 14 });
    return () => {
      removeMapLayers(layersRef.current);
      layersRef.current = [];
    };
  }, [items, clusterProjects]);

  return <div ref={containerRef} style={{ height, borderRadius: 12, overflow: "hidden" }} />;
}
