// Fixed server error messages mapped to locale keys. The API contract is unchanged: the raw text still arrives in
// ApiError.detail and stays available in the collapsed technical details. Unknown messages get a generic line.
import type { MsgKey } from "../i18n";
import type { ApiError } from "./api";

const KNOWN: [RegExp, MsgKey][] = [
  [/^no scenario id in analyze response$/, "imp.noId"],
  [/^topology approval required/i, "err.approvalRequired"],
  [/^topology changed since approval/i, "err.approvalStale"],
  [/^topology has not been generated/i, "err.noTopology"],
  [/^尚未部署/, "err.notDeployed"],
  [/^(scenario not found\.?|找不到情境)$/i, "err.noScenario"],
  [/^action not found$/i, "err.noAction"],
  [/^relation not found$/i, "err.noRelation"],
  [/^missing item not found\.?$/i, "err.noMissingItem"],
  [/^no stored source( file)? for this scenario\.?$/i, "err.noSource"],
  [/^no validation report exists/i, "err.noReport"],
  [/^generated compose not found$/i, "err.noRangeFiles"],
  [/^could not write generated compose/i, "err.rangeFilesWrite"],
  [/^could not derive dependencies/i, "err.depsFailed"],
  [/^could not generate a valid topology/i, "err.topologyFailed"],
  [/^cti analysis failed/i, "err.analysisFailed"],
  [/^supplement text must not be empty/i, "err.supplementEmpty"],
  [/^host_id or service_id is required/i, "err.supplementTarget"],
  [/^field and value must be provided together/i, "err.fieldValue"],
  [/^request body must be a json stix bundle/i, "err.notStix"],
  [/^檔案超過/, "err.fileTooBig"],
  [/^檔案是空的/, "err.fileEmpty"],
  [/^解析後沒有取得任何文字/, "err.pdfNoText"],
  [/^這個檔案不是 PDF/, "err.fileType"],
  [/^無法解析這個 PDF/, "err.pdfParse"],
  [/^伺服器未安裝 pdftotext/, "err.pdfUnsupported"],
  [/^PDF 解析逾時/, "err.pdfTimeout"],
];

export function knownErrorKey(error: Pick<ApiError, "detail">): MsgKey | null {
  const d = (error.detail ?? "").trim();
  return KNOWN.find(([re]) => re.test(d))?.[1] ?? null;
}
