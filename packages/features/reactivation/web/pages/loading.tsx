import { Card, Skeleton } from "../components/kit";

export default function Loading() {
  return (
    <div className="dp-stack" role="status" aria-label="Loading the overview">
      <div className="dp-head">
        <div>
          <Skeleton width={120} height={26} />
          <div style={{ marginTop: 8 }}>
            <Skeleton width={200} height={14} />
          </div>
        </div>
        <Skeleton width={96} height={36} />
      </div>
      <div className="dp-tiles">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <Skeleton width={110} height={12} />
            <div style={{ marginTop: 12 }}>
              <Skeleton width="70%" height={28} />
            </div>
          </Card>
        ))}
      </div>
      <Card>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} style={{ padding: "12px 0" }}>
            <Skeleton height={18} />
          </div>
        ))}
      </Card>
    </div>
  );
}
