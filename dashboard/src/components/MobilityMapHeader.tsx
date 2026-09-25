export function MobilityMapHeader() {
  return (
    <div className="map-card__header">
      <div>
        <p className="eyebrow">Spatial evidence</p>
        <h2 id="map-heading">Catchment overlap</h2>
      </div>
      <div className="map-legend" aria-label="Map legend">
        <span>
          <i className="legend-dot legend-dot--existing" />Existing
        </span>
        <span>
          <i className="legend-dot legend-dot--candidate" />Candidate
        </span>
        <span>
          <i className="legend-line" />Shared flow
        </span>
      </div>
    </div>
  );
}
