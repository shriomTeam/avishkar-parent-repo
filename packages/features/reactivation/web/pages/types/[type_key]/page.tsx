import { TypeDetail } from "../../../components/type-detail";

export default async function TypePage({ params }: { params: Promise<{ type_key: string }> }) {
  const { type_key } = await params;
  return <TypeDetail typeKey={type_key} />;
}
