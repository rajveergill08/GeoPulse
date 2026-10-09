interface MobilityMapHeaderProps {
  showH3?: boolean;
}

export function MobilityMapHeader({showH3 = false}: MobilityMapHeaderProps) {
  return (
    <div className="map-card__header">
      <div>
        <p className="eyebrow">Spatial evidence</p>
        <h2 id="map-heading">{showH3 ? 'Catchments & citywide footfall' : 'Catchment overlap'}</h2>
      </div>
      <div className="map-legend" aria-label="Map legend">
        <span>
          <i className="legend-dot legend-dot--existing" />Existing
        </span>
        <span>
          <i className="legend-dot legend-dot--candidate" />Candidate
        </span>
        <span>
          <i className="legend-line" />Overlap link
        </span>
        {showH3 ? <span>3D H3 cells · not store visits</span> : null}
      </div>
    </div>
  );
}
