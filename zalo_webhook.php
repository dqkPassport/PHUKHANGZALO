<?php
/**
 * ZALO WEBHOOK PROXY (VIETNAM IP)
 * PKĐK MEDIC PHÚ KHANG - medicphukhang.com
 * URL Google Apps Script: https://script.google.com/macros/s/AKfycbxt2Zj-HVA_vgAqtTTZMw474Jq5DWWBD96IKOZM9czCEe7PRuqKZJZVEz4BL019gtAm2Q/exec
 */

// 1. Đường dẫn Google Apps Script của bạn
$google_script_url = "https://script.google.com/macros/s/AKfycbxt2Zj-HVA_vgAqtTTZMw474Jq5DWWBD96IKOZM9czCEe7PRuqKZJZVEz4BL019gtAm2Q/exec";

// Thiết lập phản hồi JSON
header('Content-Type: application/json; charset=utf-8');

$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'POST') {
    // Đọc dữ liệu từ Zalo
    $zalo_raw_data = file_get_contents('php://input');
    
    if (empty($zalo_raw_data)) {
        http_response_code(400);
        echo json_encode(["status" => "error", "message" => "Empty payload"]);
        exit;
    }

    // Chuyển tiếp sang Google Apps Script
    $ch = curl_init($google_script_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $zalo_raw_data);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        'Content-Type: application/json',
        'Content-Length: ' . strlen($zalo_raw_data)
    ]);
    
    $response = curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    
    if (curl_errno($ch)) {
        $error_msg = curl_error($ch);
        curl_close($ch);
        http_response_code(500);
        echo json_encode(["status" => "error", "message" => "cURL Error: " . $error_msg]);
        exit;
    }
    
    curl_close($ch);
    
    // Trả kết quả cho Zalo
    http_response_code($http_code);
    echo $response;

} else {
    // Kiểm tra hoạt động bằng trình duyệt
    http_response_code(200);
    echo json_encode([
        "status" => "active",
        "message" => "Zalo Webhook Proxy is running for Medic Phu Khang!",
        "timestamp" => date('Y-m-d H:i:s')
    ]);
}
?>