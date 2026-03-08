/**
 * API functions for file attachment operations.
 */

import { apiClient } from "./client";
import type { TicketAttachment } from "@/types";

export async function uploadAttachment(data: {
  ticket: string;
  message?: string;
  file: File;
}): Promise<TicketAttachment> {
  const formData = new FormData();
  formData.append("ticket", data.ticket);
  if (data.message) {
    formData.append("message", data.message);
  }
  formData.append("file", data.file);
  formData.append("filename", data.file.name);
  formData.append("content_type", data.file.type || "application/octet-stream");
  formData.append("file_size", String(data.file.size));

  const response = await apiClient.post<TicketAttachment>(
    "/attachments/",
    formData,
    {
      headers: { "Content-Type": "multipart/form-data" },
    },
  );
  return response.data;
}
