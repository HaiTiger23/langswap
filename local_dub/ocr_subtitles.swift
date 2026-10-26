import Foundation
import Vision
import AppKit

struct Line: Codable { let text: String; let confidence: Float; let x: Double; let y: Double; let width: Double; let height: Double }
struct Frame: Codable { let file: String; let lines: [Line] }
var result: [Frame] = []
let allScreen = CommandLine.arguments.contains("--all")
for path in CommandLine.arguments.dropFirst().filter({ $0 != "--all" }) {
    autoreleasepool {
        do {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            request.usesLanguageCorrection = true
            request.minimumTextHeight = 0.014
            let handler = VNImageRequestHandler(url: URL(fileURLWithPath:path),options:[:])
            try handler.perform([request])
            var lines: [Line] = []
            for observation in request.results ?? [] {
                guard let candidate=observation.topCandidates(1).first else { continue }
                let rect=observation.boundingBox
                if !allScreen && (rect.midY < 0.05 || rect.midY > 0.48) { continue }
                if !candidate.string.unicodeScalars.contains(where: { $0.value>=0x3400 && $0.value<=0x9fff }) { continue }
                lines.append(Line(text:candidate.string,confidence:candidate.confidence,x:rect.minX,y:rect.minY,width:rect.width,height:rect.height))
            }
            result.append(Frame(file:path,lines:lines.sorted{$0.y > $1.y}))
        } catch { result.append(Frame(file:path,lines:[])) }
    }
}
let data=try JSONEncoder().encode(result)
FileHandle.standardOutput.write(data)
