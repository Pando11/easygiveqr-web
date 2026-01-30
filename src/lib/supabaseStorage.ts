import { getSupabaseAdmin } from "./supabaseAdmin";

/**
 * Upload file to Supabase Storage
 * 
 * @param bucketName - Name of the storage bucket
 * @param filePath - Path within the bucket (e.g., "qr/EGQR-123.png")
 * @param fileBuffer - File content as Buffer
 * @param contentType - MIME type (e.g., "image/png")
 * @returns Public URL to the uploaded file
 */
export async function uploadToSupabaseStorage(
  bucketName: string,
  filePath: string,
  fileBuffer: Buffer,
  contentType: string
): Promise<{ url: string; error?: string }> {
  try {
    const supabase = getSupabaseAdmin();

    // Upload file
    const { data, error } = await supabase.storage
      .from(bucketName)
      .upload(filePath, fileBuffer, {
        contentType,
        upsert: true, // Overwrite if exists
      });

    if (error) {
      console.error("[Supabase Storage] Upload failed", {
        bucket: bucketName,
        path: filePath,
        error: error.message,
      });
      return { url: "", error: error.message };
    }

    // Get public URL
    const { data: urlData } = supabase.storage
      .from(bucketName)
      .getPublicUrl(filePath);

    return { url: urlData.publicUrl };
  } catch (err: any) {
    console.error("[Supabase Storage] Unexpected error", err);
    return { url: "", error: err?.message || "Unknown error" };
  }
}

/**
 * Check if storage bucket exists and is accessible
 */
export async function checkStorageBucket(bucketName: string): Promise<boolean> {
  try {
    const supabase = getSupabaseAdmin();
    const { data, error } = await supabase.storage.listBuckets();

    if (error) {
      console.error("[Supabase Storage] Failed to list buckets", {
        error: error.message,
      });
      return false;
    }

    return data?.some((bucket) => bucket.name === bucketName) || false;
  } catch (err: any) {
    console.error("[Supabase Storage] Error checking bucket", err);
    return false;
  }
}
