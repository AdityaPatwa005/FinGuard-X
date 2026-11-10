import { DataBanner } from '../components/DataStates'

export default function GeospatialIntelligence() {
  return <div className="ops-page">
    <DataBanner title="Location intelligence is not available from current records" tag="CAPABILITY GAP">No map, heatmap or geographic inference is generated from account or transaction endpoints.</DataBanner>
    <section className="panel geo-capability-panel">
      <div className="geo-empty-symbol" aria-hidden="true">◎</div>
      <span className="data-scope-tag">NO LOCATION RECORDS</span>
      <h2>There is no location data to plot</h2>
      <p>The current transaction model and normalized outbox event do not contain device coordinates, IP-derived location, login location or transaction location. FinGuard X will not infer a physical location from a beneficiary or transfer endpoint.</p>
      <div className="geo-data-requirements">
        <article><span className="geo-kind">PHYSICAL DEVICE / LOGIN</span><strong>Not persisted</strong><p>Would require a separately sourced, timestamped device or login location with provenance and accuracy.</p></article>
        <article><span className="geo-kind">TRANSACTION LOCATION</span><strong>Not persisted</strong><p>Would require explicit transaction-origin location data, kept distinct from beneficiary or destination account details.</p></article>
      </div>
      <small>No synthetic coordinates are shown. This page becomes useful when location data is explicitly added to the event contract and persisted with its source and meaning.</small>
    </section>
  </div>
}
